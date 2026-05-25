import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QClipboard,
    QColor,
    QFont,
    QGuiApplication,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import (
    checkout_branch,
    delete_untracked,
    discard_unstaged,
    head_sha,
    list_branches,
    pull_ff_only,
    push_preview,
    stage_all,
    stage_file,
    unstage_all,
    unstage_file,
)
from ..git_actions import (
    commit as git_commit,
)
from ..git_actions import (
    fetch as git_fetch,
)
from ..git_status import GitFile, GitStatus, get_diff, get_status
from ..models import Workspace
from . import theme

log = logging.getLogger(__name__)


STATUS_COLOR = {
    "modificado": "#e0b86a",
    "mod (idx+ws)": "#e0b86a",
    "adicionado": "#5ac35a",
    "deletado": "#d57272",
    "renomeado": "#7aa6e6",
    "copiado": "#7aa6e6",
    "novo": "#888",
}

POLL_INTERVAL_MS = 30_000

# UserRole keys
T_GROUP = "group"
T_FILE = "file"
T_REPO = "repo"


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fingerprint_statuses(statuses: dict[str, GitStatus]) -> tuple:
    """Tupla hashável que captura o estado visível dos repos no painel.
    Usado pra pular rebuild da árvore quando o poll dispara sem mudanças."""
    return tuple(
        (
            folder,
            st.is_repo,
            st.branch,
            st.ahead,
            st.behind,
            st.error,
            tuple((f.status, f.path) for f in st.files),
        )
        for folder, st in statuses.items()
    )


class _DiffHighlighter(QSyntaxHighlighter):
    """Highlighter de diff unified — só aplica formato à linha visível
    via Qt (re-highlight incremental do framework). Substitui o loop
    manual O(n) que rodava em todas as QTextBlock a cada troca de
    arquivo."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self.plus = QTextCharFormat()
        self.plus.setForeground(QColor("#5ac35a"))
        self.minus = QTextCharFormat()
        self.minus.setForeground(QColor("#d57272"))
        self.header = QTextCharFormat()
        self.header.setForeground(QColor("#7aa6e6"))

    def highlightBlock(self, text: str) -> None:
        if not text:
            return
        # Headers de hunk/file primeiro (prefixos de 2-4 chars) — antes do +/-
        # pra "+++" / "---" não cair no caso single-char.
        if (
            text.startswith("+++")
            or text.startswith("---")
            or text.startswith("@@")
            or text.startswith("diff ")
            or text.startswith("index ")
        ):
            self.setFormat(0, len(text), self.header)
            return
        c = text[0]
        if c == "+":
            self.setFormat(0, len(text), self.plus)
        elif c == "-":
            self.setFormat(0, len(text), self.minus)


class GitPanel(QWidget):
    """Painel estilo IntelliJ Commit:
    - QTreeWidget agrupado por repo, com sub-grupos "Changes" e "Unversioned"
    - Cada arquivo tem checkbox; o commit usa só os marcados
    - Área de commit no rodapé (mensagem multilinha + botão Commit)
    - Diff inline opcional (toggle no header)
    - Auto-refresh via QFileSystemWatcher + poll a cada 30s
    """

    open_file_requested = Signal(str)
    # Emitido após cada commit local. Args: (workspace_id, folder, sha, message)
    # sha vai vazio se não conseguirmos resolver o HEAD pós-commit — assinante
    # deve tratar como "houve commit mesmo sem detalhe".
    commit_created = Signal(str, str, str, str)
    # Resumo pro header do painel (branch + nº de mudanças). RichText.
    # O RightDock conecta isso no PanelFrame.set_header_extra.
    header_summary_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workspace: Workspace | None = None
        self._statuses: dict[str, GitStatus] = {}
        self._status_fingerprint: tuple = ()
        self._has_any_repo: bool = False
        self._diff_visible: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Toolbar topo — duas linhas: branch/contador em cima, ações de git
        # (refresh, fetch, pull, PR, push, diff, console) embaixo, pra caberem
        # sem espremer a branch num painel estreito.
        toolbar = QVBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)
        branch_row = QHBoxLayout()
        branch_row.setSpacing(6)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)
        self._make_toolbar(branch_row, actions_row)
        toolbar.addLayout(branch_row)
        toolbar.addLayout(actions_row)
        outer.addLayout(toolbar)

        # Splitter vertical: tree em cima, diff embaixo (oculto por padrão)
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(True)
        split.setHandleWidth(6)
        split.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6;"
            "}"
            "QTreeWidget::item { padding: 2px 4px; color: #d0d0d0; }"
            "QTreeWidget::item:hover { background: #2a3142; color: #fff; }"
            "QTreeWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_single_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        split.addWidget(self._tree)

        self._diff = QPlainTextEdit()
        self._diff.setReadOnly(True)
        self._diff.setPlaceholderText("Clique num arquivo pra ver o diff.")
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._diff.setFont(mono)
        self._diff.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #d0d0d0; padding: 4px;"
            "}"
        )
        self._diff.setVisible(False)
        self._diff_highlighter = _DiffHighlighter(self._diff.document())
        split.addWidget(self._diff)
        split.setSizes([400, 0])
        self._tree_diff_split = split

        # Área de commit
        commit_area = self._build_commit_area()

        # Console de atividade git (commits, merges, checkouts, pulls, fetch)
        # — alimentado pelas ações do app e pelo reflog (captura também o que
        # as skills/terminal fazem). Oculto até ter algo / toggle na toolbar.
        self._activity = QPlainTextEdit()
        self._activity.setReadOnly(True)
        self._activity.setVisible(False)
        self._activity.setMinimumHeight(60)
        self._activity.setPlaceholderText(
            "Atividade git aparece aqui (commits, merges, checkouts, pulls)…"
        )
        amono = QFont("monospace")
        amono.setStyleHint(QFont.StyleHint.Monospace)
        self._activity.setFont(amono)
        self._activity.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #cfcfcf; padding: 4px;"
            "}"
        )

        # Splitter vertical maior: tree/diff, área de commit e console de
        # atividade — todos redimensionáveis arrastando os handles. O console
        # fica colapsado (size 0) enquanto oculto.
        main_split = QSplitter(Qt.Orientation.Vertical)
        main_split.setChildrenCollapsible(False)
        main_split.setHandleWidth(6)
        main_split.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )
        main_split.addWidget(split)
        main_split.addWidget(commit_area)
        main_split.addWidget(self._activity)
        main_split.setStretchFactor(0, 1)
        main_split.setStretchFactor(1, 0)
        main_split.setStretchFactor(2, 0)
        main_split.setSizes([400, 110, 0])
        self._main_split = main_split
        outer.addWidget(main_split, stretch=1)
        # Byte offset já lido de cada reflog (.git/logs/HEAD) por repo.
        self._reflog_pos: dict[str, int] = {}

        # Watchers + poll
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._schedule_refresh)
        self._watcher.directoryChanged.connect(self._schedule_refresh)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self.refresh)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.refresh)

    # ---------- construção ----------

    def _make_toolbar(self, branch_row: QHBoxLayout, actions_row: QHBoxLayout) -> None:
        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        # Branch picker inline — mostra a branch atual (ou "(multi)") com
        # ícone code-branch. Click abre o branch picker do primeiro repo.
        self._branch_btn = QPushButton("  —")
        self._branch_btn.setIcon(_ic("fa5s.code-branch", color="#e5b53b"))
        self._branch_btn.setIconSize(_QS(11, 11))
        self._branch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._branch_btn.setToolTip("Trocar branch do primeiro repo deste workspace")
        # Branch destacada em amarelo pra ficar visível à primeira vista,
        # tanto em mono-repo quanto em multi-repo.
        self._branch_btn.setStyleSheet(
            "QPushButton { background: rgba(229,181,59,0.08); color: #e5b53b; "
            "border: 1px solid rgba(229,181,59,0.35); border-radius: 4px; "
            "padding: 2px 8px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { border-color: #e5b53b; color: #ffd35c; "
            "background: rgba(229,181,59,0.16); }"
            "QPushButton:disabled { color: #666; border-color: #2c2c2c; "
            "background: transparent; font-weight: 400; }"
        )
        self._branch_btn.clicked.connect(self._on_branch_btn_clicked)
        branch_row.addWidget(self._branch_btn)

        self._counter = QLabel()
        self._counter.setStyleSheet("color: #b0b0b0; font-size: 11px; padding: 0 4px;")
        branch_row.addWidget(self._counter)
        branch_row.addStretch()

        btn_css = (
            "QPushButton { background: transparent; color: #aaa; "
            "border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #6aa9e0; border-color: #3d6ea8; }"
            "QPushButton:disabled { color: #444; }"
        )

        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        def _icon_btn(qta_name: str, tooltip: str, slot, label: str = "") -> QPushButton:
            b = QPushButton(f"  {label}" if label else "")
            b.setIcon(_ic(qta_name, color="#aaa"))
            b.setIconSize(_QS(13, 13))
            b.setToolTip(tooltip)
            b.setStyleSheet(btn_css)
            b.clicked.connect(slot)
            return b

        actions_row.addWidget(_icon_btn("fa5s.sync-alt", "Atualizar", self.refresh))
        actions_row.addWidget(_icon_btn("fa5s.exchange-alt", "Fetch (todos os repos)", self._do_fetch_all))
        actions_row.addWidget(_icon_btn("fa5s.cloud-download-alt", "Pull ff-only (todos os repos)", self._do_pull_all))
        # PR button guardado em self pra poder desabilitar enquanto gh roda
        self._pr_btn = _icon_btn(
            "fa5s.code-branch",
            "Abrir Pull Request no GitHub (branch atual → base)",
            self._do_open_pr,
            label="PR",
        )
        actions_row.addWidget(self._pr_btn)
        actions_row.addWidget(
            _icon_btn(
                "fa5s.cloud-upload-alt",
                "Push — mostra commits e arquivos antes de enviar",
                self._do_push,
                label="Push",
            )
        )
        self._toggle_diff_btn = _icon_btn(
            "fa5s.eye", "Mostrar / esconder diff", self._toggle_diff
        )
        actions_row.addWidget(self._toggle_diff_btn)
        self._toggle_log_btn = _icon_btn(
            "fa5s.terminal",
            "Mostrar / esconder console de atividade git",
            self._toggle_activity,
        )
        actions_row.addWidget(self._toggle_log_btn)
        actions_row.addStretch()

    def _build_commit_area(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(4)

        self._msg = QPlainTextEdit()
        self._msg.setPlaceholderText("Mensagem do commit…")
        self._msg.setMinimumHeight(56)
        self._msg.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 4px; color: #e6e6e6; padding: 4px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        v.addWidget(self._msg, stretch=1)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)

        primary_qss = (
            "QPushButton {"
            "  background: #3d6ea8; color: #fff;"
            "  border: 0; border-radius: 4px; padding: 4px 14px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #4a82c5; }"
            "QPushButton:disabled { background: #2a2a2a; color: #555; }"
        )
        ghost_qss = (
            "QPushButton {"
            "  background: #1f1f1f; color: #c8c8c8;"
            "  border: 1px solid #2c2c2c; border-radius: 4px;"
            "  padding: 4px 12px;"
            "}"
            "QPushButton:hover { border-color: #3d6ea8; color: #6aa9e0; }"
            "QPushButton:disabled { color: #555; border-color: #2a2a2a; }"
        )

        self._commit_btn = QPushButton("Commit")
        self._commit_btn.setStyleSheet(primary_qss)
        self._commit_btn.clicked.connect(self._do_commit)
        bottom.addWidget(self._commit_btn)

        # Botão "Commit + Push" — commita e em seguida faz push da branch
        # atual (com upstream automático se faltar).
        self._commit_push_btn = QPushButton("Commit + Push")
        self._commit_push_btn.setStyleSheet(ghost_qss)
        self._commit_push_btn.setToolTip(
            "Commit + push da branch atual (cria upstream se necessário)"
        )
        self._commit_push_btn.clicked.connect(self._do_commit_and_push)
        bottom.addWidget(self._commit_push_btn)

        # Botão "Push" puro — abre o diálogo de push sem commitar nada
        # (pros casos em que o usuário já commitou e só quer enviar).
        self._push_btn = QPushButton("Push")
        self._push_btn.setStyleSheet(ghost_qss)
        self._push_btn.setToolTip(
            "Push da branch atual — mostra commits e arquivos antes de enviar"
        )
        self._push_btn.clicked.connect(lambda: self._do_push())
        bottom.addWidget(self._push_btn)

        bottom.addStretch()
        v.addLayout(bottom)
        return box

    # ---------- workspace ----------

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        self.refresh()

    def has_any_repo(self) -> bool:
        return self._has_any_repo

    # ---------- refresh ----------

    def _schedule_refresh(self, *_args) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        # Drena reflogs antes de qualquer early-return — captura atividade
        # (merge/commit/checkout/pull) de qualquer origem, inclusive skills.
        self._drain_reflogs()

        # Preserva o estado de checked dos arquivos (rel_path) por repo
        prev_unchecked: dict[str, set[str]] = {}
        for i in range(self._tree.topLevelItemCount()):
            repo_item = self._tree.topLevelItem(i)
            data = repo_item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") != T_REPO:
                continue
            folder = data["folder"]
            unchecked: set[str] = set()
            self._collect_unchecked_files(repo_item, unchecked)
            prev_unchecked[folder] = unchecked

        # Coleta primeiro, decide depois: se nada mudou desde o último
        # refresh, evita rebuild da árvore (preserva scroll/seleção e zera
        # custo de paint do QTreeWidget). Fingerprint = tuple imutável das
        # infos visíveis por repo.
        if not self.workspace or not self.workspace.folders:
            new_statuses: dict[str, GitStatus] = {}
        else:
            new_statuses = {
                folder: get_status(folder) for folder in self.workspace.folders
            }

        new_fp = _fingerprint_statuses(new_statuses)
        if new_fp == self._status_fingerprint and self._tree.topLevelItemCount():
            # Estado idêntico — só atualiza referência e sai. Evita rebuild
            # da árvore inteira durante polls quando nada mudou no repo.
            self._statuses = new_statuses
            return

        self._tree.blockSignals(True)
        self._tree.clear()
        self._statuses = new_statuses
        self._status_fingerprint = new_fp

        if not self.workspace or not self.workspace.folders:
            self._counter.setText("")
            self.header_summary_changed.emit("")
            self._has_any_repo = False
            self._update_watches([])
            self._tree.blockSignals(False)
            self._update_commit_button()
            return

        repo_folders: list[str] = []
        total_files = 0
        for folder in self.workspace.folders:
            status = self._statuses[folder]
            if not status.is_repo:
                continue
            repo_folders.append(folder)
            self._add_repo(folder, status, prev_unchecked.get(folder, set()))
            total_files += len(status.files)

        self._has_any_repo = bool(repo_folders)
        if not self._has_any_repo:
            placeholder = QTreeWidgetItem(["(nenhuma pasta é repo git)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            self._counter.setText("")
            self._branch_btn.setText("  —")
            self._branch_btn.setEnabled(False)
            self.header_summary_changed.emit("")
            self._poll_timer.stop()
        else:
            if total_files == 0:
                self._counter.setText("<span style='color:#5ac35a'>✓ limpo</span>")
            else:
                self._counter.setText(
                    f"<span style='color:#e5b53b'>● {total_files} alteração(ões)</span>"
                )
            self._counter.setTextFormat(Qt.TextFormat.RichText)
            # Atualiza label do branch picker: 1 repo → mostra branch;
            # >1 repos com mesma branch → idem; senão → "(multi)".
            branches = {s.branch for s in self._statuses.values() if s.is_repo and s.branch}
            if not branches:
                self._branch_btn.setText("  —")
                self._branch_btn.setEnabled(False)
                branch_text = ""
            elif len(branches) == 1:
                br = next(iter(branches))
                self._branch_btn.setText(f"  {br[:24]}")
                self._branch_btn.setEnabled(True)
                branch_text = br
            else:
                self._branch_btn.setText("  (multi)")
                self._branch_btn.setToolTip(
                    "Multi-repo com branches diferentes — click pra escolher repo"
                )
                self._branch_btn.setEnabled(True)
                branch_text = "(multi)"
            # Resumo pro header do painel: "⎇ branch · N mudança(s)" ou
            # "⎇ branch · ✓ limpo". Cores espelham o toolbar (branch âmbar,
            # contador âmbar, limpo verde).
            if branch_text:
                br_html = (
                    f"<span style='color:{theme.WARNING}'>⎇ {branch_text[:24]}</span>"
                )
                if total_files == 0:
                    self.header_summary_changed.emit(
                        f"{br_html} <span style='color:{theme.TEXT_FAINT}'>·</span> "
                        f"<span style='color:{theme.SUCCESS}'>✓ limpo</span>"
                    )
                else:
                    self.header_summary_changed.emit(
                        f"{br_html} <span style='color:{theme.TEXT_FAINT}'>·</span> "
                        f"<span style='color:{theme.WARNING}'>● {total_files} mudança(s)</span>"
                    )
            else:
                self.header_summary_changed.emit("")
            if not self._poll_timer.isActive():
                self._poll_timer.start()

        self._tree.blockSignals(False)
        self._update_watches(repo_folders)
        self._update_commit_button()

    def _collect_unchecked_files(self, parent: QTreeWidgetItem, out: set[str]) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Unchecked:
                    out.add(data["rel_path"])
            else:
                self._collect_unchecked_files(child, out)

    def _update_watches(self, repo_folders: list[str]) -> None:
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        targets: list[str] = []
        for folder in repo_folders:
            git_dir = Path(folder) / ".git"
            if not git_dir.exists():
                continue
            for name in ("index", "HEAD", "FETCH_HEAD", "ORIG_HEAD"):
                f = git_dir / name
                if f.exists():
                    targets.append(str(f))
            heads = git_dir / "refs" / "heads"
            if heads.is_dir():
                targets.append(str(heads))
            # Reflog: dispara o drain quando merge/commit/checkout/pull ocorre.
            reflog = git_dir / "logs" / "HEAD"
            if reflog.exists():
                targets.append(str(reflog))
        if targets:
            self._watcher.addPaths(targets)

    # ---------- console de atividade ----------

    def _toggle_activity(self) -> None:
        show = not self._activity.isVisible()
        self._activity.setVisible(show)
        # Ao mostrar, garante uma altura inicial no splitter (do contrário Qt
        # daria só o minimumHeight); ao esconder, colapsa o painel.
        sizes = self._main_split.sizes()
        if len(sizes) == 3:
            if show and sizes[2] == 0:
                take = max(120, sizes[0] // 4)
                sizes[0] = max(120, sizes[0] - take)
                sizes[2] = take
            elif not show:
                sizes[0] += sizes[2]
                sizes[2] = 0
            self._main_split.setSizes(sizes)

    def _log_activity(self, text: str, color: str | None = None) -> None:
        """Acrescenta uma linha ao console de atividade (auto-mostra)."""
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        body = _html(text)
        line = (
            f"<span style='color:#666'>{ts}</span> "
            + (f"<span style='color:{color}'>{body}</span>" if color else body)
        )
        self._activity.appendHtml(line)
        self._activity.verticalScrollBar().setValue(
            self._activity.verticalScrollBar().maximum()
        )
        if not self._activity.isVisible():
            self._toggle_activity()

    def _drain_reflogs(self) -> None:
        """Lê o que foi acrescentado a cada `.git/logs/HEAD` desde a última
        leitura e joga no console. Na primeira vez só registra o tamanho
        (não reproduz histórico). Captura atividade de qualquer origem."""
        if not self.workspace:
            return
        for folder in self.workspace.folders:
            reflog = Path(folder) / ".git" / "logs" / "HEAD"
            if not reflog.is_file():
                continue
            key = str(reflog)
            try:
                size = reflog.stat().st_size
            except OSError:
                continue
            prev = self._reflog_pos.get(key)
            if prev is None or size < prev:
                # Primeiro contato (ou reflog truncado por gc): sincroniza
                # sem reproduzir o que já existia.
                self._reflog_pos[key] = size
                continue
            if size == prev:
                continue
            try:
                with open(reflog, "rb") as f:
                    f.seek(prev)
                    data = f.read()
            except OSError:
                continue
            self._reflog_pos[key] = size
            repo = Path(folder).name
            for raw in data.decode("utf-8", "replace").splitlines():
                formatted = self._format_reflog(raw, repo)
                if formatted:
                    self._log_activity(*formatted)

    @staticmethod
    def _format_reflog(line: str, repo: str) -> tuple[str, str] | None:
        """Converte uma linha de reflog em (texto, cor). None se inválida.

        Formato: `<old> <new> <ident...> <ts> <tz>\\t<mensagem>` onde a
        mensagem é tipo "merge x: ...", "commit: ...", "checkout: ...".
        """
        if "\t" not in line:
            return None
        meta, msg = line.split("\t", 1)
        parts = meta.split(" ")
        if len(parts) < 2:
            return None
        new_sha = parts[1][:7]
        action = msg.split(":", 1)[0].split(" ", 1)[0].lower()
        color = {
            "merge": "#7aa6e6",
            "pull": "#7aa6e6",
            "rebase": "#7aa6e6",
            "commit": theme.SUCCESS if hasattr(theme, "SUCCESS") else "#5ac35a",
            "checkout": "#e0b86a",
            "reset": "#d57272",
            "revert": "#d57272",
            "cherry-pick": "#7aa6e6",
            "clone": "#5ac35a",
        }.get(action, "#b0b0b0")
        return (f"⎇ {repo}: {msg}  ({new_sha})", color)

    # ---------- árvore ----------

    def _add_repo(
        self,
        folder: str,
        status: GitStatus,
        prev_unchecked: set[str],
    ) -> None:
        name = Path(folder).name
        ahead_behind = ""
        if status.ahead or status.behind:
            bits = []
            if status.ahead:
                bits.append(f"↑{status.ahead}")
            if status.behind:
                bits.append(f"↓{status.behind}")
            ahead_behind = " " + "".join(bits)
        marker = "✓ limpo" if not status.files else f"{len(status.files)} mudança(s)"
        repo_item = QTreeWidgetItem(
            [f"{name}  ·  {status.branch}{ahead_behind}  ·  {marker}"]
        )
        repo_item.setData(
            0, Qt.ItemDataRole.UserRole, {"type": T_REPO, "folder": folder}
        )
        f = repo_item.font(0)
        f.setBold(True)
        repo_item.setFont(0, f)
        if status.error:
            repo_item.setForeground(0, QBrush(QColor("#d57272")))
            repo_item.setText(0, repo_item.text(0) + f"  ({status.error})")

        # Agrupar em Changes / Unversioned
        changes: list[GitFile] = []
        untracked: list[GitFile] = []
        for gf in status.files:
            if gf.is_untracked:
                untracked.append(gf)
            else:
                changes.append(gf)

        if changes:
            grp = self._make_group_item(folder, "Changes", len(changes))
            repo_item.addChild(grp)
            for gf in changes:
                child = self._make_file_item(folder, gf, prev_unchecked)
                grp.addChild(child)
            grp.setExpanded(True)
        if untracked:
            grp = self._make_group_item(folder, "Unversioned Files", len(untracked))
            repo_item.addChild(grp)
            for gf in untracked:
                child = self._make_file_item(folder, gf, prev_unchecked)
                grp.addChild(child)
            grp.setExpanded(True)

        repo_item.setExpanded(True)
        self._tree.addTopLevelItem(repo_item)

    def _make_group_item(self, folder: str, name: str, count: int) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"{name}  ({count})"])
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        item.setForeground(0, QBrush(QColor("#bbb")))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {"type": T_GROUP, "folder": folder, "name": name},
        )
        return item

    def _make_file_item(
        self,
        folder: str,
        gf: GitFile,
        prev_unchecked: set[str],
    ) -> QTreeWidgetItem:
        rel = gf.path
        parent_path = ""
        name = rel
        if "/" in rel:
            parent_path, name = rel.rsplit("/", 1)
        text = f"{gf.status}  {name}"
        if parent_path:
            text += f"   {parent_path}"
        item = QTreeWidgetItem([text])
        color = STATUS_COLOR.get(gf.label(), "#aaa")
        item.setForeground(0, QBrush(QColor(color)))
        mono = item.font(0)
        mono.setFamily("monospace")
        item.setFont(0, mono)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        check_state = (
            Qt.CheckState.Unchecked
            if rel in prev_unchecked
            else Qt.CheckState.Checked
        )
        item.setCheckState(0, check_state)
        item.setToolTip(0, f"{gf.label()}  ·  {Path(folder) / rel}")
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": T_FILE,
                "folder": folder,
                "rel_path": rel,
                "path": str(Path(folder) / rel),
                "is_staged": gf.is_staged,
                "is_unstaged": gf.is_unstaged,
                "is_untracked": gf.is_untracked,
            },
        )
        return item

    # ---------- interação ----------

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int) -> None:
        self._update_commit_button()

    def _on_single_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") != T_FILE:
            return
        if not self._diff_visible:
            return
        folder = data["folder"]
        rel = data["rel_path"]
        text = get_diff(folder, rel, staged=data["is_staged"] and not data["is_unstaged"])
        # setPlainText dispara o QSyntaxHighlighter automaticamente — Qt
        # re-formata só os blocks afetados, sem precisar varrer o doc.
        self._diff.setPlainText(text)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") == T_FILE:
            self.open_file_requested.emit(data["path"])

    def _show_diff_for(self, item: QTreeWidgetItem) -> None:
        if not self._diff_visible:
            self._toggle_diff()
        self._on_single_click(item, 0)

    def _toggle_diff(self) -> None:
        self._diff_visible = not self._diff_visible
        self._diff.setVisible(self._diff_visible)
        if self._diff_visible:
            self._tree_diff_split.setSizes([300, 200])
        else:
            self._tree_diff_split.setSizes([400, 0])

    # ---------- collecting checked files ----------

    def _collect_checked_files(self) -> dict[str, list[str]]:
        """Devolve {folder: [rel_path, ...]} pra cada repo com arquivos marcados."""
        out: dict[str, list[str]] = {}
        for i in range(self._tree.topLevelItemCount()):
            repo = self._tree.topLevelItem(i)
            data = repo.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") != T_REPO:
                continue
            folder = data["folder"]
            files: list[str] = []
            self._walk_collect_checked(repo, files)
            if files:
                out[folder] = files
        return out

    def _walk_collect_checked(
        self, parent: QTreeWidgetItem, out: list[str]
    ) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.append(data["rel_path"])
            else:
                self._walk_collect_checked(child, out)

    def _update_commit_button(self) -> None:
        checked = self._collect_checked_files()
        total = sum(len(v) for v in checked.values())
        enabled = total > 0
        self._commit_btn.setEnabled(enabled)
        self._commit_btn.setText(
            "Commit" if total == 0 else f"Commit ({total})"
        )
        if hasattr(self, "_commit_push_btn"):
            self._commit_push_btn.setEnabled(enabled)

    # ---------- context menu ----------

    def _on_context_menu(self, pos: QPoint) -> None:
        clicked = self._tree.itemAt(pos)
        selected = self._tree.selectedItems()
        if clicked is not None and clicked not in selected:
            # Right-click em item não-selecionado: usa só o clicado
            # (Qt não muda seleção em right-click por padrão; sem isso o menu
            # cairia no item antigo da seleção em vez do que o usuário clicou.)
            items = [clicked]
        else:
            items = selected or ([clicked] if clicked else [])
        if not items:
            return

        menu = QMenu(self)
        # Classifica os items selecionados
        file_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_FILE
        ]
        group_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_GROUP
        ]
        repo_items = [
            i for i in items
            if (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("type") == T_REPO
        ]

        if file_items:
            self._build_file_menu(menu, file_items)
        elif group_items:
            self._build_group_menu(menu, group_items)
        elif repo_items:
            self._build_repo_menu(menu, repo_items)

        if menu.actions():
            menu.exec_(self._tree.viewport().mapToGlobal(pos))

    def _build_file_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        # Pega dados consolidados
        first_data = items[0].data(0, Qt.ItemDataRole.UserRole)
        any_untracked = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_untracked")
            for i in items
        )
        any_unstaged = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_unstaged")
            for i in items
        )
        any_staged = any(
            (i.data(0, Qt.ItemDataRole.UserRole) or {}).get("is_staged")
            for i in items
        )
        n = len(items)
        suffix = "" if n == 1 else f" ({n} arquivos)"

        if len(items) == 1:
            menu.addAction(
                self._action(
                    "Abrir no editor",
                    lambda: self.open_file_requested.emit(first_data["path"]),
                )
            )
            if not first_data.get("is_untracked"):
                menu.addAction(
                    self._action(
                        "👁 Ver diff",
                        lambda _=False, it=items[0]: self._show_diff_for(it),
                    )
                )
            menu.addSeparator()

        if any_untracked or any_unstaged:
            menu.addAction(
                self._action(f"+ Add{suffix}", lambda: self._stage_items(items))
            )
        if any_staged:
            menu.addAction(
                self._action(f"− Unstage{suffix}", lambda: self._unstage_items(items))
            )

        menu.addSeparator()
        if any_unstaged:
            menu.addAction(
                self._action(
                    f"↶ Rollback mudanças{suffix}",
                    lambda: self._rollback_items(items),
                )
            )
        if any_untracked:
            menu.addAction(
                self._action(
                    f"✕ Delete{suffix}",
                    lambda: self._delete_items(items),
                )
            )

    def _build_group_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        group_name = items[0].data(0, Qt.ItemDataRole.UserRole).get("name", "")
        items[0].data(0, Qt.ItemDataRole.UserRole).get("folder", "")
        if "Unversioned" in group_name:
            menu.addAction(
                self._action("+ Add todos", lambda: self._stage_group(items[0]))
            )
        elif "Changes" in group_name:
            menu.addAction(
                self._action("+ Stage todos", lambda: self._stage_group(items[0]))
            )
            menu.addAction(
                self._action("− Unstage todos", lambda: self._unstage_group(items[0]))
            )
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "↶ Rollback todos",
                    lambda: self._rollback_group(items[0]),
                )
            )

    def _build_repo_menu(
        self, menu: QMenu, items: list[QTreeWidgetItem]
    ) -> None:
        folder = items[0].data(0, Qt.ItemDataRole.UserRole).get("folder", "")
        menu.addAction(
            self._action("⤓ Pull (ff-only)", lambda: self._do_pull_one(folder))
        )
        menu.addAction(
            self._action("⇡⇣ Fetch", lambda: self._do_fetch_one(folder))
        )
        menu.addAction(
            self._action("⬆ Push…", lambda: self._do_push(folders=[folder]))
        )
        self._add_switch_branch_menu(menu, folder)
        menu.addSeparator()
        menu.addAction(
            self._action("+ Stage tudo", lambda: stage_all(folder) and self.refresh())
        )
        menu.addAction(
            self._action(
                "− Unstage tudo", lambda: unstage_all(folder) and self.refresh()
            )
        )
        menu.addSeparator()
        from ..settings import Settings
        cmd = (Settings.load().file_open_command or "code").strip() or "code"
        editor_name = "VS Code" if cmd.split()[0] == "code" else cmd.split()[0]
        menu.addAction(
            self._action(
                f"⧉ Abrir com {editor_name}",
                lambda: self._open_in_editor(folder),
            )
        )
        menu.addAction(
            self._action(
                "📁 Abrir pasta",
                lambda: self._open_folder(folder),
            )
        )

    def _add_switch_branch_menu(self, menu: QMenu, folder: str) -> None:
        # Antes era submenu populado lazy, mas com dezenas/centenas de
        # branches vira um scroll inoperante — agora abre diálogo com
        # filtro incremental.
        menu.addAction(
            self._action(
                "⎇ Trocar branch…",
                lambda: self._open_branch_picker(folder),
            )
        )

    def _on_branch_btn_clicked(self) -> None:
        """Click no badge da branch: abre branch picker do 1º repo do
        workspace. Multi-repo precisaria de um picker de repo antes."""
        repo_folders = [
            f for f, s in self._statuses.items() if s.is_repo
        ]
        if not repo_folders:
            return
        self._open_branch_picker(repo_folders[0])

    def _open_branch_picker(self, folder: str) -> None:
        from .branch_picker_dialog import BranchPickerDialog

        branches, current = list_branches(folder)
        if not branches:
            QMessageBox.information(
                self, "Trocar branch", f"{Path(folder).name}: sem branches."
            )
            return
        dlg = BranchPickerDialog(branches, current, Path(folder).name, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.selected_branch:
            self._do_checkout_branch(folder, dlg.selected_branch)

    def _do_checkout_branch(self, folder: str, branch: str) -> None:
        ok, out = checkout_branch(folder, branch)
        if not ok:
            QMessageBox.warning(
                self,
                "Checkout falhou",
                f"{Path(folder).name} → {branch}\n\n{out[:2000]}",
            )
        self.refresh()

    def _open_in_editor(self, folder: str) -> None:
        from ..launchers import LauncherError, open_file_in_editor
        from ..settings import Settings
        try:
            open_file_in_editor(folder, Settings.load())
        except LauncherError as e:
            QMessageBox.warning(self, "Abrir no editor", str(e))

    def _open_folder(self, folder: str) -> None:
        from ..errors import LaunchError
        from ..services.system_open import open_in_file_manager
        try:
            open_in_file_manager(folder)
        except LaunchError as e:
            QMessageBox.warning(self, "Falha ao abrir pasta", str(e))

    def _action(self, text: str, slot) -> QAction:
        # Parent obrigatório: sem isso o QAction é coletado pelo GC antes do
        # QMenu abrir (Qt.addAction(QAction) não toma posse).
        a = QAction(text, self)
        a.triggered.connect(slot)
        return a

    # ---------- handlers do menu ----------

    def _stage_items(self, items: list[QTreeWidgetItem]) -> None:
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = stage_file(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Stage", "?", False, "\n".join(errors))
        self.refresh()

    def _unstage_items(self, items: list[QTreeWidgetItem]) -> None:
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = unstage_file(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Unstage", "?", False, "\n".join(errors))
        self.refresh()

    def _rollback_items(self, items: list[QTreeWidgetItem]) -> None:
        names = [i.data(0, Qt.ItemDataRole.UserRole)["rel_path"] for i in items]
        reply = QMessageBox.question(
            self,
            "Rollback de mudanças",
            "Vai descartar mudanças locais (irreversível) em:\n\n"
            + "\n".join(names[:20])
            + (f"\n... e mais {len(names)-20}" if len(names) > 20 else "")
            + "\n\nContinuar?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = discard_unstaged(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Rollback", "?", False, "\n".join(errors))
        self.refresh()

    def _delete_items(self, items: list[QTreeWidgetItem]) -> None:
        names = [i.data(0, Qt.ItemDataRole.UserRole)["rel_path"] for i in items]
        reply = QMessageBox.question(
            self,
            "Deletar arquivos untracked",
            "Vai apagar do disco (irreversível):\n\n"
            + "\n".join(names[:20])
            + (f"\n... e mais {len(names)-20}" if len(names) > 20 else "")
            + "\n\nContinuar?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        errors = []
        for it in items:
            d = it.data(0, Qt.ItemDataRole.UserRole)
            ok, out = delete_untracked(d["folder"], d["rel_path"])
            if not ok:
                errors.append(f"{d['rel_path']}: {out}")
        if errors:
            self._notify("Delete", "?", False, "\n".join(errors))
        self.refresh()

    def _collect_group_files(self, group_item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        return [group_item.child(i) for i in range(group_item.childCount())]

    def _stage_group(self, group_item: QTreeWidgetItem) -> None:
        self._stage_items(self._collect_group_files(group_item))

    def _unstage_group(self, group_item: QTreeWidgetItem) -> None:
        self._unstage_items(self._collect_group_files(group_item))

    def _rollback_group(self, group_item: QTreeWidgetItem) -> None:
        self._rollback_items(self._collect_group_files(group_item))

    def _do_fetch_one(self, folder: str) -> None:
        ok, out = git_fetch(folder)
        repo = Path(folder).name
        self._log_activity(
            f"⇣ {repo}: fetch {'ok' if ok else 'falhou'}",
            theme.SUCCESS if ok else theme.DANGER,
        )
        self._notify("Fetch", folder, ok, out)
        self.refresh()

    def _do_pull_one(self, folder: str) -> None:
        ok, out = pull_ff_only(folder)
        self._notify("Pull", folder, ok, out)
        self.refresh()

    # ---------- ações git ----------

    def _do_commit(self) -> tuple[bool, list[str]]:
        """Commit atual. Retorna (sucesso, folders_que_commitaram_ok)
        pra permitir encadear push depois."""
        checked = self._collect_checked_files()
        if not checked:
            return (False, [])
        message = self._msg.toPlainText().strip()
        if not message:
            QMessageBox.warning(
                self,
                "Mensagem vazia",
                "Escreva uma mensagem de commit antes.",
            )
            self._msg.setFocus()
            return (False, [])

        if len(checked) > 1:
            reply = QMessageBox.question(
                self,
                "Múltiplos repos",
                f"Vai commitar em {len(checked)} repos com a mesma mensagem. Confirma?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return (False, [])

        errors: list[str] = []
        committed_folders: list[str] = []
        for folder, files in checked.items():
            # 1. Reset staging area pro estado limpo
            unstage_all(folder)
            # 2. Stage só os arquivos marcados
            stage_failed = False
            for rel in files:
                ok, out = stage_file(folder, rel)
                if not ok:
                    errors.append(f"{Path(folder).name}: stage {rel} falhou — {out}")
                    stage_failed = True
                    break
            if stage_failed:
                continue
            # 3. Commit
            ok, out = git_commit(folder, message)
            if not ok:
                errors.append(f"{Path(folder).name}: commit falhou — {out}")
            else:
                committed_folders.append(folder)
                if self.workspace is not None:
                    sha = head_sha(folder)
                    self.commit_created.emit(self.workspace.id, folder, sha, message)

        if errors:
            QMessageBox.warning(self, "Erros no commit", "\n\n".join(errors)[:2000])
        else:
            self._msg.clear()
        self.refresh()
        return (not errors, committed_folders)

    def _do_commit_and_push(self) -> None:
        """Faz commit e em seguida abre o diálogo de push pros folders que
        receberam commit (mostra commits + arquivos antes de enviar)."""
        ok, folders = self._do_commit()
        if not folders:
            return
        self._do_push(folders=folders)

    def _do_push(self, folders: list[str] | None = None) -> None:
        """Abre o diálogo estilo IntelliJ com os commits/arquivos a enviar e,
        se confirmado, faz o push de cada repo.

        `folders` restringe aos repos passados (usado pelo Commit+Push);
        senão considera todos os repos do workspace.
        """
        if not self.workspace:
            return
        targets = folders if folders is not None else list(self.workspace.folders)
        previews = []
        for folder in targets:
            pv = push_preview(folder)
            if pv.error or pv.is_empty:
                continue
            previews.append(pv)

        if not previews:
            QMessageBox.information(
                self,
                "Nada a enviar",
                "Nenhum commit pendente de push nos repositórios do workspace.",
            )
            return

        from .push_dialog import PushCommitsDialog

        # O diálogo executa o push e mostra a saída num console interno;
        # aqui só damos refresh ao fechar.
        dlg = PushCommitsDialog(previews, self)
        dlg.exec()
        self.refresh()

    def _do_fetch_all(self) -> None:
        if not self.workspace:
            return
        results = []
        for folder in self.workspace.folders:
            if folder not in self._statuses or not self._statuses[folder].is_repo:
                continue
            ok, out = git_fetch(folder)
            results.append(f"{Path(folder).name}: {'OK' if ok else out[:200]}")
        if results:
            QMessageBox.information(self, "Fetch", "\n".join(results)[:2000])
        self.refresh()

    def _do_pull_all(self) -> None:
        if not self.workspace:
            return
        results = []
        for folder in self.workspace.folders:
            if folder not in self._statuses or not self._statuses[folder].is_repo:
                continue
            ok, out = pull_ff_only(folder)
            results.append(f"{Path(folder).name}: {'OK' if ok else out[:200]}")
        if results:
            QMessageBox.information(self, "Pull", "\n".join(results)[:2000])
        self.refresh()

    def _pick_pr_folder(self) -> str | None:
        """Escolhe o folder pra abrir PR: primária se for repo, senão
        primeira pasta que é repo. None se nenhum."""
        if not self.workspace:
            return None
        primary = self.workspace.primary_folder()
        if primary and self._statuses.get(primary) and self._statuses[primary].is_repo:
            return primary
        for folder in self.workspace.folders:
            st = self._statuses.get(folder)
            if st and st.is_repo:
                return folder
        return None

    def _set_pr_busy(self, busy: bool, label: str = "") -> None:
        """Liga/desliga estado de busy do botão PR: troca label, desabilita,
        WaitCursor global e força um repaint pra usuário ver o feedback
        durante a operação síncrona."""
        if busy:
            self._pr_btn.setEnabled(False)
            self._pr_btn.setText(label or "⏳ PR")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()
            self._pr_btn.setEnabled(True)
            self._pr_btn.setText("⮏ PR")
        # Força paint imediato pra o estado do botão refletir antes da
        # próxima chamada bloqueante (push, gh pr view, gh pr create)
        QApplication.processEvents()

    def _do_open_pr(self) -> None:
        # Imports locais — pesadinho (subprocess via gh) e não usado no
        # caminho comum; mantém startup do painel leve
        from ..pr_actions import (
            create_pr_github,
            find_existing_pr,
            gh_available,
            push_with_upstream,
        )
        from ..pr_draft import build_draft_for_folder
        from ..pr_provider import branch_state, detect_github
        from ..services.system_open import open_url
        from .open_pr_dialog import OpenPullRequestDialog

        folder = self._pick_pr_folder()
        if not folder:
            QMessageBox.warning(
                self,
                "Sem repo",
                "Nenhuma pasta do workspace é um repositório git.",
            )
            return

        gh = detect_github(folder)
        if not gh:
            QMessageBox.warning(
                self,
                "Remote não é GitHub",
                "O remote `origin` deste repo não é GitHub — só GitHub é "
                "suportado por enquanto.",
            )
            return

        if not gh_available():
            QMessageBox.warning(
                self,
                "gh CLI ausente",
                "O binário `gh` não está no PATH. Instale o GitHub CLI "
                "(`paru -S github-cli`) e faça `gh auth login`.",
            )
            return

        state = branch_state(folder)
        if state.error:
            QMessageBox.warning(self, "Estado do branch", state.error)
            return
        if not state.current:
            QMessageBox.warning(self, "HEAD inválido", "Sem branch atual.")
            return
        if state.current == state.base:
            QMessageBox.warning(
                self,
                "Está no base",
                f"Você está em `{state.base}` — troque pra uma feature branch "
                "antes de abrir PR.",
            )
            return
        if state.dirty:
            reply = QMessageBox.question(
                self,
                "Working tree sujo",
                "Existem mudanças não-commitadas. Elas NÃO entram no PR. "
                "Quer continuar mesmo assim?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if state.ahead == 0:
            QMessageBox.warning(
                self,
                "Sem commits",
                f"`{state.current}` não tem commits acima de `{state.base}`. "
                "Faça commit antes de abrir PR.",
            )
            return

        # Checa PR existente ANTES de oferecer push/dialog — se já tem,
        # usuário só quer abrir a URL. Evita duplicado e roundtrip
        try:
            self._set_pr_busy(True, "🔍 PR")
            existing = find_existing_pr(folder, state.current)
        finally:
            self._set_pr_busy(False)
        if existing and existing.state == "OPEN":
            reply = QMessageBox.question(
                self,
                "PR já existe",
                f"Já existe PR aberto pra <b>{state.current}</b>:<br>"
                f"#{existing.number} — {existing.url}<br><br>"
                "Abrir no navegador?",
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    open_url(existing.url)
                except Exception as e:
                    log.warning("Falha abrindo URL: %s", e)
            return

        # Garante upstream — gh pr create exige a branch publicada
        if not state.has_upstream:
            reply = QMessageBox.question(
                self,
                "Sem upstream",
                f"`{state.current}` não tem upstream. Faço `git push -u "
                f"origin {state.current}` agora?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                self._set_pr_busy(True, "⬆ push")
                ok, out = push_with_upstream(folder, state.current)
            finally:
                self._set_pr_busy(False)
            if not ok:
                QMessageBox.warning(
                    self, "Push falhou", out[:2000] or "(sem output)"
                )
                return

        draft = build_draft_for_folder(folder, state.base, fallback_title=state.current)

        dialog = OpenPullRequestDialog(
            repo_label=gh.full_name,
            branch=state.current,
            base=state.base,
            title=draft.title,
            body=draft.body,
            parent=self,
        )
        if not dialog.exec():
            return
        title, base, body, is_draft = dialog.values()
        if not title:
            QMessageBox.warning(self, "Título vazio", "Título do PR é obrigatório.")
            return

        try:
            self._set_pr_busy(True, "⏳ PR")
            result = create_pr_github(folder, title, body, base, draft=is_draft)
        finally:
            self._set_pr_busy(False)
        if not result.ok:
            QMessageBox.warning(self, "gh pr create falhou", result.error[:2000])
            return

        # Copia URL pra clipboard pra usuário colar no Slack/etc
        if result.url:
            QGuiApplication.clipboard().setText(result.url, QClipboard.Mode.Clipboard)

        # Pergunta se quer abrir no navegador agora
        reply = QMessageBox.question(
            self,
            "PR aberto",
            f"<b>{title}</b><br><br>"
            f"{result.url}<br><br>"
            "URL copiada pro clipboard. Abrir no navegador?",
        )
        if reply == QMessageBox.StandardButton.Yes and result.url:
            try:
                open_url(result.url)
            except Exception as e:
                log.warning("Falha abrindo URL: %s", e)


def open_path_in_editor(path: str, editor_command: str = "code") -> None:
    """Compat: delega pro services.system_open.open_in_editor."""
    from ..services.system_open import open_in_editor
    open_in_editor(path, editor_command)
