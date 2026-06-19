import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtCore import QRect
from PySide6.QtGui import (
    QAction,
    QBrush,
    QClipboard,
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyledItemDelegate,
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
from ..git_worktree import resolve_git_dirs
from ..models import Workspace
from . import theme
from .diff_web_view import DiffWebView
from .spinner import Spinner

log = logging.getLogger(__name__)


def _collect_numstat(folder: str) -> dict[str, tuple[int, int]]:
    """{rel_path: (added, removed)} combinando working-tree e staged. Linhas
    binárias ('-') viram (0, 0). Alimenta o ±linhas do feed ao vivo; é
    best-effort (renames simples normalizados pro caminho novo)."""
    out: dict[str, tuple[int, int]] = {}
    for extra in ([], ["--cached"]):
        try:
            r = subprocess.run(
                ["git", "diff", "--numstat", *extra],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            a, d, path = parts
            added = int(a) if a.isdigit() else 0
            removed = int(d) if d.isdigit() else 0
            # rename "old => new"; "{a => b}/c" fica cru (raro no feed).
            if " => " in path and "{" not in path:
                path = path.split(" => ", 1)[1]
            out[path] = (added, removed)
    return out


class _StatusScanSignals(QObject):
    # epoch, {folder: GitStatus}, {folder: {path: (added, removed)}}
    done = Signal(int, dict, dict)


class _WatchDirsSignals(QObject):
    done = Signal(tuple, list)  # key (tuple de repo_folders), dirs


class _WatchDirsTask(QRunnable):
    """Roda o os.walk dos working trees fora da UI thread — em monorepos
    grandes montar a lista de watch dirs (até _WATCH_DIR_CAP) leva segundos
    e travava a troca de seleção de workspace. Só devolve a lista; quem
    mexe no QFileSystemWatcher é a UI thread (dona do watcher)."""

    def __init__(
        self, key: tuple, folders: list[str], signals: _WatchDirsSignals
    ) -> None:
        super().__init__()
        self._key = key
        self._folders = folders
        self._signals = signals

    def run(self) -> None:
        dirs: list[str] = []
        try:
            for folder in self._folders:
                dirs.extend(_worktree_watch_dirs(folder))
        except Exception:
            log.exception("git_panel: walk de watch dirs falhou")
        self._signals.done.emit(self._key, dirs)


class _StatusScanTask(QRunnable):
    """Roda `get_status` (subprocess `git status`) fora da UI thread pra cada
    pasta, mais `git diff --numstat` pras ±linhas do feed. Só devolve dados;
    o rebuild da árvore e o feed ficam na UI thread."""

    def __init__(self, epoch: int, folders: list[str], signals: _StatusScanSignals) -> None:
        super().__init__()
        self.epoch = epoch
        self.folders = folders
        self.signals = signals

    def run(self) -> None:
        statuses: dict[str, GitStatus] = {}
        numstats: dict[str, dict[str, tuple[int, int]]] = {}
        for folder in self.folders:
            try:
                statuses[folder] = get_status(folder)
            except Exception:
                log.exception("git_panel: get_status falhou em %s", folder)
                statuses[folder] = GitStatus(folder=folder, is_repo=False)
            try:
                numstats[folder] = _collect_numstat(folder)
            except Exception:
                numstats[folder] = {}
        self.signals.done.emit(self.epoch, statuses, numstats)


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
T_FOLDER = "folder"  # separador de pasta na lista de arquivos

# Pastas que o watcher do worktree nunca observa (pesadas/irrelevantes pro
# feed) + teto de diretórios pra não estourar o limite de inotify.
_WATCH_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", ".idea", ".gradle", "coverage", ".turbo", "vendor",
    ".tox", ".cache", "out", "bin", "obj",
}
_WATCH_DIR_CAP = 1500

# Glyph + cor por código de status (mesma paleta do STATUS_COLOR/diálogo de
# push) usados nas linhas do feed ao vivo.
_FEED_GLYPH = {"A": "+", "M": "~", "D": "−", "R": "→", "C": "→", "T": "~"}
_FEED_COLOR = {
    "A": "#5ac35a", "M": "#e0b86a", "D": "#d57272",
    "R": "#7aa6e6", "C": "#7aa6e6", "T": "#e0b86a",
}


def _worktree_watch_dirs(folder: str) -> list[str]:
    """Diretórios do working tree a observar. O QFileSystemWatcher não é
    recursivo, então cada subpasta entra na lista; podamos pastas pesadas
    (_WATCH_SKIP_DIRS) e limitamos a _WATCH_DIR_CAP. inotify num diretório
    reporta create/delete/modify dos arquivos contidos — é o que dispara o
    feed quando um arquivo é salvo."""
    dirs: list[str] = []
    try:
        for root, subdirs, _files in os.walk(folder):
            subdirs[:] = [d for d in subdirs if d not in _WATCH_SKIP_DIRS]
            dirs.append(root)
            if len(dirs) >= _WATCH_DIR_CAP:
                break
    except OSError:
        pass
    return dirs


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _status_code(xy: str) -> str:
    """Reduz o status porcelain de 2 chars (XY) a uma letra A/M/D/R/C pra
    colorir o arquivo igual ao diálogo de push (que usa `--name-status`)."""
    if xy == "??":
        return "A"  # novo no working tree → trata como adicionado
    for code in ("D", "R", "C", "A", "M", "T"):
        if code in xy:
            return code
    return (xy.strip() or "M")[0]


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


class _StatsDelegate(QStyledItemDelegate):
    """Pinta a coluna de stats (+N -M) em verde e vermelho.

    O dado UserRole da coluna 1 é uma tupla (added: int, removed: int).
    Renderiza da direita pra esquerda: '-M' (vermelho) mais à direita,
    '+N' (verde) à esquerda dele, alinhados à margem direita da célula.
    """

    _ADD = QColor("#5ac35a")
    _DEL = QColor("#d57272")

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        super().paint(painter, option, index)
        raw = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(raw, tuple) or len(raw) != 2:
            return
        added, removed = raw
        if not added and not removed:
            return
        painter.save()
        painter.setFont(option.font)
        fm = painter.fontMetrics()
        r = option.rect
        x = r.right() - 4

        if removed:
            s = f"-{removed}"
            w = fm.horizontalAdvance(s)
            painter.setPen(self._DEL)
            painter.drawText(
                QRect(x - w, r.top(), w, r.height()),
                Qt.AlignmentFlag.AlignVCenter,
                s,
            )
            x = x - w - 5

        if added:
            s = f"+{added}"
            w = fm.horizontalAdvance(s)
            painter.setPen(self._ADD)
            painter.drawText(
                QRect(x - w, r.top(), w, r.height()),
                Qt.AlignmentFlag.AlignVCenter,
                s,
            )

        painter.restore()


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
        # Quando não-None, o painel inspeciona estas pastas em vez de
        # workspace.folders — usado pra seguir o worktree do console ativo.
        self._folders_override: list[str] | None = None
        self._statuses: dict[str, GitStatus] = {}
        self._status_fingerprint: tuple = ()
        self._has_any_repo: bool = False
        self._diff_visible: bool = False
        # Arquivo atualmente exibido no diff rico: (folder, rel_path, staged)
        # None quando não há diff aberto.
        self._shown_diff: tuple[str, str, bool] | None = None
        # Linhas de contexto no diff: 3 (padrão) ou grande (arquivo inteiro)
        self._diff_context: int = 3

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
        self._tree.setColumnCount(2)
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
        # Coluna 0 = filename (estica pra preencher); coluna 1 = stats +/- (fixo)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(1, 72)
        # Delegate que renderiza +N (verde) -M (vermelho) na coluna de stats
        self._stats_delegate = _StatsDelegate(self._tree)
        self._tree.setItemDelegateForColumn(1, self._stats_delegate)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_single_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        split.addWidget(self._tree)

        # Container do diff: header fino (arquivo + toggles) + DiffWebView
        diff_container = QWidget()
        diff_container.setVisible(False)
        diff_vlay = QVBoxLayout(diff_container)
        diff_vlay.setContentsMargins(0, 0, 0, 0)
        diff_vlay.setSpacing(0)

        # Header do diff pane — linha com nome do arquivo, toggles de formato
        # e botão de expandir contexto
        diff_hdr = QWidget()
        diff_hdr.setStyleSheet(
            "QWidget { background: #1a1a1a; border-bottom: 1px solid #2a2a2a; }"
            "QPushButton { background: transparent; color: #888; border: 1px solid transparent;"
            " border-radius: 3px; padding: 1px 7px; font-size: 11px; }"
            "QPushButton:hover { color: #ccc; border-color: #444; }"
            "QPushButton:checked { background: #2d4a70; color: #7ab8f5; border-color: #3d6ea8; }"
        )
        hdr_lay = QHBoxLayout(diff_hdr)
        hdr_lay.setContentsMargins(6, 2, 6, 2)
        hdr_lay.setSpacing(4)

        self._diff_filename = QLabel("")
        self._diff_filename.setStyleSheet("color: #9aa0a6; font-size: 11px; background: transparent;")
        hdr_lay.addWidget(self._diff_filename)
        hdr_lay.addStretch()

        # Toggles inline ↔ lado-a-lado
        self._diff_inline_btn = QPushButton("Inline")
        self._diff_inline_btn.setCheckable(True)
        self._diff_inline_btn.setChecked(True)
        self._diff_inline_btn.setToolTip("Diff unificado (inline)")
        self._diff_inline_btn.clicked.connect(lambda: self._set_diff_format("line-by-line"))
        hdr_lay.addWidget(self._diff_inline_btn)

        self._diff_side_btn = QPushButton("Lado a lado")
        self._diff_side_btn.setCheckable(True)
        self._diff_side_btn.setToolTip("Diff lado a lado com scroll sincronizado")
        self._diff_side_btn.clicked.connect(lambda: self._set_diff_format("side-by-side"))
        hdr_lay.addWidget(self._diff_side_btn)

        # Separador visual
        sep = QLabel("·")
        sep.setStyleSheet("color: #444; background: transparent;")
        hdr_lay.addWidget(sep)

        self._diff_ctx_btn = QPushButton("Expandir")
        self._diff_ctx_btn.setCheckable(True)
        self._diff_ctx_btn.setToolTip("Mostrar arquivo completo / só hunks")
        self._diff_ctx_btn.clicked.connect(self._toggle_diff_context)
        hdr_lay.addWidget(self._diff_ctx_btn)

        diff_vlay.addWidget(diff_hdr)

        self._diff_web = DiffWebView(diff_container)
        diff_vlay.addWidget(self._diff_web, stretch=1)

        self._diff_container = diff_container
        split.addWidget(diff_container)
        split.setSizes([400, 0])
        self._tree_diff_split = split

        # Área de commit
        commit_area = self._build_commit_area()

        # Feed de atividade ao vivo do worktree — fluxo cronológico dos arquivos
        # tocados (criados/modificados/deletados) com ±linhas, estilo terminal.
        # É o "hero" do painel: fica no topo do splitter e visível por padrão.
        self._feed = QPlainTextEdit()
        self._feed.setReadOnly(True)
        self._feed.setMaximumBlockCount(200)  # descarta linhas antigas
        self._feed.setMinimumHeight(80)
        self._feed.setPlaceholderText(
            "Mudanças no worktree aparecem aqui em tempo real…"
        )
        fmono = QFont("monospace")
        fmono.setStyleHint(QFont.StyleHint.Monospace)
        self._feed.setFont(fmono)
        self._feed.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #0e0e0e; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #cfcfcf; padding: 4px;"
            "}"
        )

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
        main_split.addWidget(self._feed)
        main_split.addWidget(split)
        main_split.addWidget(commit_area)
        main_split.addWidget(self._activity)
        main_split.setStretchFactor(0, 0)  # feed
        main_split.setStretchFactor(1, 1)  # tree/diff
        main_split.setStretchFactor(2, 0)  # commit
        main_split.setStretchFactor(3, 0)  # atividade git
        main_split.setSizes([200, 320, 110, 0])
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

        # Coleta de git status assíncrona: pool dedicado (max 2, igual ao
        # RepoStatusPoller — subprocess+disk-bound), epoch pra descartar scans
        # obsoletos e spinner "atualizando…" no contador.
        self._status_pool = QThreadPool()
        self._status_pool.setMaxThreadCount(2)
        self._status_epoch = 0
        self._status_signals = _StatusScanSignals()
        self._status_signals.done.connect(self._apply_statuses)
        self._prev_unchecked: dict[str, set[str]] = {}
        self._counter_before_scan = ""
        self._status_spinner = Spinner(parent=self)
        self._status_spinner.tick.connect(self._on_status_spinner_tick)

        # Feed ao vivo: estado por pasta {folder: {path: (code, +, -)}} pra
        # detectar deltas entre scans; chave do conjunto de pastas pra resetar
        # o baseline ao trocar de workspace/console.
        self._prev_event_state: dict[str, dict[str, tuple]] = {}
        self._feed_folders_key: tuple = ()
        # Diretórios do worktree atualmente observados (caros de montar — só
        # recomputados quando o conjunto de repos muda, e em thread do pool).
        self._wt_dirs: list[str] = []
        self._wt_dirs_key: tuple = ()
        self._watch_dirs_signals = _WatchDirsSignals()
        self._watch_dirs_signals.done.connect(self._on_watch_dirs_ready)

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
            "fa5s.eye",
            "Mostrar / esconder painel de diff inline",
            self._toggle_diff,
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

    def set_folders_override(self, folders: list[str] | None) -> None:
        """Faz o painel inspecionar `folders` (ex.: worktree do console ativo)
        em vez de workspace.folders. None volta ao comportamento do workspace."""
        new = list(folders) if folders is not None else None
        if new == self._folders_override:
            return
        self._folders_override = new
        self.refresh()

    def _active_folders(self) -> list[str]:
        """Pastas a inspecionar: override do console ativo, senão as do workspace."""
        if self._folders_override is not None:
            return self._folders_override
        if self.workspace and self.workspace.folders:
            return list(self.workspace.folders)
        return []

    def has_any_repo(self) -> bool:
        return self._has_any_repo

    # ---------- refresh ----------

    def _schedule_refresh(self, *_args) -> None:
        self._refresh_timer.start()

    def refresh(self) -> None:
        # Drena reflogs antes de qualquer early-return — captura atividade
        # (merge/commit/checkout/pull) de qualquer origem, inclusive skills.
        # Barato (stat/read de arquivo), fica síncrono.
        self._drain_reflogs()

        # Preserva o estado de checked dos arquivos (rel_path) por repo —
        # lido da árvore atual (UI thread) pra reaplicar no rebuild.
        self._prev_unchecked = {}
        for i in range(self._tree.topLevelItemCount()):
            repo_item = self._tree.topLevelItem(i)
            data = repo_item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") != T_REPO:
                continue
            folder = data["folder"]
            unchecked: set[str] = set()
            self._collect_unchecked_files(repo_item, unchecked)
            self._prev_unchecked[folder] = unchecked

        active_folders = self._active_folders()
        self._status_epoch += 1
        if not active_folders:
            # Sem pastas → aplica direto, sem thread.
            self._status_spinner.stop()
            self._apply_statuses(self._status_epoch, {}, {})
            return

        # Coleta `get_status` (subprocess) numa thread — não bloqueia a UI.
        # Mostra "atualizando…" no contador enquanto roda.
        if not self._status_spinner.is_running():
            self._counter_before_scan = self._counter.text()
        self._counter.setText(f"{self._status_spinner.frame()} atualizando…")
        self._status_spinner.start()
        self._status_pool.start(
            _StatusScanTask(self._status_epoch, list(active_folders), self._status_signals)
        )

    def _on_status_spinner_tick(self, frame: str) -> None:
        self._counter.setText(f"{frame} atualizando…")

    def _apply_statuses(self, epoch: int, new_statuses: dict, numstats: dict) -> None:
        # Descarta scan obsoleto (override/seleção mudou no meio do caminho).
        if epoch != self._status_epoch:
            return
        self._status_spinner.stop()
        prev_unchecked = self._prev_unchecked
        active_folders = self._active_folders()

        # Feed ao vivo: roda ANTES do early-return de fingerprint, porque o
        # fingerprint ignora ±linhas — editar de novo um arquivo já "M" não
        # mexe na árvore, mas precisa aparecer no feed. Ao trocar o conjunto
        # de pastas (workspace/console), zera o baseline pra não misturar.
        folders_key = tuple(active_folders)
        if folders_key != self._feed_folders_key:
            self._feed.clear()
            self._prev_event_state = {}
            self._feed_folders_key = folders_key
        self._process_feed_events(active_folders, new_statuses, numstats or {})

        # Refresh ao vivo do diff exibido — roda ANTES do early-return de
        # fingerprint porque o diff pode mudar sem alterar a lista de arquivos
        # (ex.: editar de novo um arquivo já "M").
        self._refresh_shown_diff(new_statuses)

        # Coleta primeiro, decide depois: se nada mudou desde o último
        # refresh, evita rebuild da árvore (preserva scroll/seleção e zera
        # custo de paint do QTreeWidget). Fingerprint = tuple imutável das
        # infos visíveis por repo.
        new_fp = _fingerprint_statuses(new_statuses)
        if new_fp == self._status_fingerprint and self._tree.topLevelItemCount():
            # Estado idêntico — só atualiza referência e restaura o contador.
            self._statuses = new_statuses
            self._counter.setText(self._counter_before_scan)
            return

        self._tree.blockSignals(True)
        self._tree.clear()
        self._statuses = new_statuses
        self._status_fingerprint = new_fp

        if not active_folders:
            self._counter.setText("")
            self.header_summary_changed.emit("")
            self._has_any_repo = False
            self._update_watches([])
            self._tree.blockSignals(False)
            self._update_commit_button()
            return

        repo_folders: list[str] = []
        total_files = 0
        for folder in active_folders:
            status = self._statuses[folder]
            if not status.is_repo:
                continue
            repo_folders.append(folder)
            self._add_repo(
                folder, status,
                prev_unchecked.get(folder, set()),
                numstats.get(folder) if numstats else None,
            )
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

    # ---------- feed ao vivo ----------

    def _process_feed_events(
        self, active_folders: list[str], statuses: dict, numstats: dict
    ) -> None:
        """Compara o estado atual (status + ±linhas) com o do scan anterior
        e emite uma linha no feed pra cada arquivo novo/alterado. Na primeira
        vez que vê uma pasta (baseline) lista o estado atual uma vez, sem
        timbre de 'agora'."""
        for folder in active_folders:
            st = statuses.get(folder)
            if st is None or not st.is_repo:
                continue
            counts = numstats.get(folder, {})
            cur: dict[str, tuple] = {}
            for f in st.files:
                code = _status_code(f.status)
                a, d = counts.get(f.path, (0, 0))
                cur[f.path] = (code, a, d)
            prev = self._prev_event_state.get(folder)
            if prev is None:
                self._feed_baseline(st, cur)
            else:
                for path, tup in cur.items():
                    if prev.get(path) != tup:
                        self._feed_event(path, tup)
            self._prev_event_state[folder] = cur

    def _feed_line(
        self, path: str, code: str, added: int, removed: int, *, baseline: bool
    ) -> str:
        glyph = _FEED_GLYPH.get(code, "~")
        color = _FEED_COLOR.get(code, "#cfcfcf")
        counts = ""
        if added or removed:
            counts = (
                f"  <span style='color:#5ac35a'>+{added}</span> "
                f"<span style='color:#d57272'>-{removed}</span>"
            )
        body = (
            f"<span style='color:{color}'>{glyph}</span> "
            f"<span style='color:{color}'>{_html(path)}</span>{counts}"
        )
        if baseline:
            return f"<span style='color:#666'>·</span> {body}"
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        return f"<span style='color:#666'>{ts}</span>  {body}"

    def _feed_baseline(self, st: GitStatus, cur: dict[str, tuple]) -> None:
        if not cur:
            return
        branch = st.branch or "?"
        sep = (
            f"<span style='color:#555'>── {_html(branch)} · "
            f"{len(cur)} mudança(s) atual(is) ──</span>"
        )
        self._feed.appendHtml(sep)
        for path, (code, a, d) in cur.items():
            self._feed.appendHtml(self._feed_line(path, code, a, d, baseline=True))
        self._feed_scroll()

    def _feed_event(self, path: str, tup: tuple) -> None:
        code, a, d = tup
        self._feed.appendHtml(self._feed_line(path, code, a, d, baseline=False))
        self._feed_scroll()

    def _feed_scroll(self) -> None:
        sb = self._feed.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _collect_unchecked_files(self, parent: QTreeWidgetItem, out: set[str]) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Unchecked:
                    out.add(data["rel_path"])
            else:
                self._collect_unchecked_files(child, out)

    def _git_watch_targets(self, repo_folders: list[str]) -> list[str]:
        """Paths dentro de .git (index/HEAD/refs/reflog) — baratos, reatados a
        cada refresh porque saves atômicos do git removem o watch."""
        targets: list[str] = []
        for folder in repo_folders:
            dirs = resolve_git_dirs(folder)
            if dirs is None:
                continue
            # Em worktree linkada git_dir != common_dir: HEAD/index/ORIG_HEAD
            # são por-worktree (git_dir); refs/heads é compartilhado (common).
            git_dir, common_dir = dirs
            for base in dict.fromkeys((git_dir, common_dir)):
                for name in ("index", "HEAD", "FETCH_HEAD", "ORIG_HEAD"):
                    f = base / name
                    if f.exists():
                        targets.append(str(f))
            heads = common_dir / "refs" / "heads"
            if heads.is_dir():
                targets.append(str(heads))
            # Reflog: dispara o drain quando merge/commit/checkout/pull ocorre.
            reflog = git_dir / "logs" / "HEAD"
            if reflog.exists():
                targets.append(str(reflog))
        return targets

    def _update_watches(self, repo_folders: list[str]) -> None:
        # 1) Diretórios do working tree — caros de montar (os.walk roda no
        #    pool, não na UI thread); só reconstrói quando o conjunto de
        #    repos muda. Até o resultado voltar só os watches de .git ficam
        #    ativos — o _poll_timer de 30s cobre eventos perdidos na janela.
        key = tuple(repo_folders)
        if key != self._wt_dirs_key:
            if self._wt_dirs:
                old = set(self._wt_dirs)
                stale = [d for d in self._watcher.directories() if d in old]
                if stale:
                    self._watcher.removePaths(stale)
            self._wt_dirs = []
            self._wt_dirs_key = key
            if repo_folders:
                self._status_pool.start(
                    _WatchDirsTask(key, list(repo_folders), self._watch_dirs_signals)
                )

        # 2) Paths do .git — reata sempre, preservando os dirs do worktree.
        wt = set(self._wt_dirs)
        stale_files = list(self._watcher.files())
        stale_git_dirs = [d for d in self._watcher.directories() if d not in wt]
        if stale_files or stale_git_dirs:
            self._watcher.removePaths(stale_files + stale_git_dirs)
        git_targets = self._git_watch_targets(repo_folders)
        if git_targets:
            self._watcher.addPaths(git_targets)

    def _on_watch_dirs_ready(self, key: tuple, dirs: list) -> None:
        """Resultado do _WatchDirsTask. Epoch-guard: se a seleção mudou
        enquanto o walk rodava, a key não bate mais e o resultado é
        descartado (mesmo idiom do _apply_statuses)."""
        if key != self._wt_dirs_key:
            return
        self._wt_dirs = list(dirs)
        if self._wt_dirs:
            self._watcher.addPaths(self._wt_dirs)

    # ---------- console de atividade ----------

    def _toggle_activity(self) -> None:
        show = not self._activity.isVisible()
        self._activity.setVisible(show)
        # Ao mostrar, garante uma altura inicial no splitter (do contrário Qt
        # daria só o minimumHeight); ao esconder, colapsa o painel.
        # Índices do _main_split: 0=feed, 1=tree/diff, 2=commit, 3=atividade.
        sizes = self._main_split.sizes()
        if len(sizes) == 4:
            if show and sizes[3] == 0:
                take = max(120, sizes[1] // 4)
                sizes[1] = max(120, sizes[1] - take)
                sizes[3] = take
            elif not show:
                sizes[1] += sizes[3]
                sizes[3] = 0
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
        for folder in self._active_folders():
            dirs = resolve_git_dirs(folder)
            if dirs is None:
                continue
            # logs/HEAD é por-worktree: vive no git_dir privado, não no common.
            reflog = dirs[0] / "logs" / "HEAD"
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
        numstats: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        ns = numstats or {}
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
        # Totais +/- para o label do repo
        total_add = sum(a for a, _ in ns.values())
        total_del = sum(d for _, d in ns.values())
        stats_str = ""
        if total_add:
            stats_str += f"  +{total_add}"
        if total_del:
            stats_str += f"  -{total_del}"
        repo_item = QTreeWidgetItem(
            [f"{name}  ·  {status.branch}{ahead_behind}  ·  {marker}{stats_str}", ""]
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
        # Linha de cabeçalho do repo ocupa a largura inteira: recupera os 72px
        # reservados (ociosos) da coluna de stats pra branch não ser cortada.
        # ElideRight corta o fim (· marcador/stats, redundante) antes da branch.
        repo_item.setFirstColumnSpanned(True)
        repo_item.setToolTip(0, repo_item.text(0))

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
            self._add_files_with_dirs(grp, folder, changes, prev_unchecked, ns)
            grp.setExpanded(True)
        if untracked:
            grp = self._make_group_item(folder, "Unversioned Files", len(untracked))
            repo_item.addChild(grp)
            self._add_files_with_dirs(grp, folder, untracked, prev_unchecked, ns)
            grp.setExpanded(True)

        repo_item.setExpanded(True)
        self._tree.addTopLevelItem(repo_item)

    def _add_files_with_dirs(
        self,
        parent: QTreeWidgetItem,
        folder: str,
        files: list[GitFile],
        prev_unchecked: set[str],
        numstats: dict[str, tuple[int, int]],
    ) -> None:
        """Insere arquivos agrupados por pasta (separadores de diretório dimmed)."""
        # Ordena por caminho para agrupar arquivos da mesma pasta
        sorted_files = sorted(files, key=lambda gf: gf.path)
        last_dir = None
        for gf in sorted_files:
            rel_dir = gf.path.rsplit("/", 1)[0] if "/" in gf.path else ""
            if rel_dir != last_dir:
                last_dir = rel_dir
                if rel_dir:
                    sep = self._make_folder_sep(rel_dir)
                    parent.addChild(sep)
            child = self._make_file_item(folder, gf, prev_unchecked, numstats)
            parent.addChild(child)

    def _make_folder_sep(self, rel_dir: str) -> QTreeWidgetItem:
        """Linha separadora de pasta — dimmed, não selecionável, sem checkbox."""
        item = QTreeWidgetItem([rel_dir, ""])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # não selecionável nem editável
        item.setForeground(0, QBrush(QColor("#585e68")))
        f = item.font(0)
        f.setFamily("monospace")
        f.setPointSizeF(f.pointSizeF() * 0.9)
        item.setFont(0, f)
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": T_FOLDER})
        return item

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
        numstats: dict[str, tuple[int, int]] | None = None,
    ) -> QTreeWidgetItem:
        rel = gf.path
        # Só o basename — o diretório pai é exibido pelo separador acima
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        color = STATUS_COLOR.get(gf.label(), "#aaa")
        item = QTreeWidgetItem([name, ""])
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
        # Coluna 1: stats +/- via delegate
        if numstats:
            added, removed = numstats.get(rel, (0, 0))
            if added or removed:
                item.setData(1, Qt.ItemDataRole.UserRole, (added, removed))
        return item

    # ---------- interação ----------

    def _on_item_changed(self, item: QTreeWidgetItem, _col: int) -> None:
        self._update_commit_button()

    def _on_single_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") != T_FILE:
            return
        folder = data["folder"]
        rel = data["rel_path"]
        staged = data["is_staged"] and not data["is_unstaged"]
        self._shown_diff = (folder, rel, staged)
        # Auto-revelar o pane de diff ao clicar num arquivo (sem precisar do toggle)
        if not self._diff_visible:
            self._toggle_diff()
        text = get_diff(folder, rel, staged=staged, context=self._diff_context)
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        self._diff_filename.setText(rel)
        self._diff_web.show_diff(text, name)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") == T_FILE:
            self.open_file_requested.emit(data["path"])

    def _show_diff_for(self, item: QTreeWidgetItem) -> None:
        # _on_single_click já auto-revela o pane — delega direto.
        self._on_single_click(item, 0)

    def _open_changes_diff(self) -> None:
        """Abre o diálogo de Changes (mesmo visual do Push) com as mudanças
        não commitadas de todos os repos; diff lado-a-lado no duplo clique."""
        repos: list[tuple[str, str, list[tuple[str, str]]]] = []
        for folder, st in self._statuses.items():
            if not st.is_repo or not st.files:
                continue
            files = [(_status_code(f.status), f.path) for f in st.files]
            repos.append((Path(folder).name, folder, files))
        if not repos:
            QMessageBox.information(
                self,
                "Sem mudanças",
                "Nenhuma mudança não commitada nos repositórios do workspace.",
            )
            return
        from .changes_dialog import ChangesDialog

        ChangesDialog(repos, self).exec()

    def _toggle_diff(self) -> None:
        self._diff_visible = not self._diff_visible
        self._diff_container.setVisible(self._diff_visible)
        if self._diff_visible:
            self._tree_diff_split.setSizes([260, 220])
            # Se já há um arquivo salvo, re-renderiza imediatamente
            if self._shown_diff and not self._diff_web.has_diff():
                folder, rel, staged = self._shown_diff
                text = get_diff(folder, rel, staged=staged, context=self._diff_context)
                name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
                self._diff_web.show_diff(text, name)
        else:
            self._tree_diff_split.setSizes([400, 0])

    def _set_diff_format(self, fmt: str) -> None:
        """Alterna o formato do diff (inline / lado-a-lado)."""
        self._diff_inline_btn.setChecked(fmt == "line-by-line")
        self._diff_side_btn.setChecked(fmt == "side-by-side")
        self._diff_web.set_output_format(fmt)

    def _toggle_diff_context(self) -> None:
        """Alterna entre contexto padrão (3 linhas) e arquivo inteiro."""
        if self._diff_ctx_btn.isChecked():
            self._diff_context = 100_000  # arquivo inteiro
            self._diff_ctx_btn.setText("Recolher")
        else:
            self._diff_context = 3
            self._diff_ctx_btn.setText("Expandir")
        if self._shown_diff and self._diff_visible:
            folder, rel, staged = self._shown_diff
            text = get_diff(folder, rel, staged=staged, context=self._diff_context)
            name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
            self._diff_web.show_diff(text, name)

    def _refresh_shown_diff(self, statuses: dict) -> None:
        """Atualiza o diff exibido se o arquivo ainda tem mudanças.

        Chamado em cada scan — antes do early-return de fingerprint — pra que
        o diff fique ao vivo mesmo quando a lista de arquivos não muda (ex.: o
        usuário salva o arquivo de novo sem commit).
        """
        if self._shown_diff is None or not self._diff_visible:
            return
        folder, rel, staged = self._shown_diff
        st = statuses.get(folder)
        if st is None or not st.is_repo:
            # Pasta saiu do conjunto ativo (troca de console/override)
            self._diff_web.clear_diff()
            self._diff_filename.setText("")
            self._shown_diff = None
            return
        paths_in_status = {gf.path for gf in st.files}
        if rel not in paths_in_status:
            # Arquivo não tem mais mudanças (commitado ou revertido)
            self._diff_web.clear_diff()
            self._diff_filename.setText("")
            self._shown_diff = None
            return
        # Re-renderiza com o conteúdo mais recente
        text = get_diff(folder, rel, staged=staged, context=self._diff_context)
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        self._diff_web.show_diff(text, name)

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
            self._action("📋 Changes (todos)", self._open_changes_diff)
        )
        menu.addSeparator()
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
        targets = folders if folders is not None else self._active_folders()
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
        for folder in self._active_folders():
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
        for folder in self._active_folders():
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
        folders = self._active_folders()
        if not folders:
            return None
        primary = folders[0]
        if primary and self._statuses.get(primary) and self._statuses[primary].is_repo:
            return primary
        for folder in folders:
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
