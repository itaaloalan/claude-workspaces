import logging
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
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
    QFontMetrics,
    QGuiApplication,
    QPainter,
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..git_actions import (
    WORKTREE,
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
from ..git_status import (
    CompareScan,
    GitFile,
    GitStatus,
    get_compare_scan,
    get_diff,
    get_diff_range,
    get_status_fresh,
)
from ..git_worktree import resolve_git_dirs
from ..models import Workspace
from .. import compare_meta
from . import theme
from .diff_web_view import DiffWebView
from .spinner import Spinner

log = logging.getLogger(__name__)


def _collect_numstat(folder: str) -> dict[str, tuple[int, int]]:
    """{rel_path: (added, removed)} combinando working-tree e staged. Linhas
    binárias ('-') viram (0, 0). Alimenta o ±linhas da árvore e do contador;
    é best-effort (renames simples normalizados pro caminho novo)."""
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
            # rename "old => new"; "{a => b}/c" fica cru (raro).
            if " => " in path and "{" not in path:
                path = path.split(" => ", 1)[1]
            out[path] = (added, removed)
    return out


class _StatusScanSignals(QObject):
    # epoch, {folder: GitStatus}, {folder: {path: (added, removed)}},
    # {folder: CompareScan} (vazio fora do modo comparação)
    done = Signal(int, dict, dict, dict)


class _WatchDirsSignals(QObject):
    done = Signal(tuple, list)  # key (tuple de repo_folders), dirs


class _CommittedScanSignals(QObject):
    done = Signal(dict)  # {folder: (upstream, merge_base_sha, [BranchFile])}


class _CommittedScanTask(QRunnable):
    """Escaneia os arquivos commitados vs upstream (COMMITTED ON BRANCH)
    fora da UI thread — git diff em monorepo pode levar segundos."""

    def __init__(self, folders: list[str], signals: _CommittedScanSignals) -> None:
        super().__init__()
        self._folders = folders
        self._signals = signals

    def run(self) -> None:
        from ..git_status import get_branch_files, upstream_ref
        out: dict = {}
        try:
            for folder in self._folders:
                up = upstream_ref(folder)
                if not up:
                    continue
                sha, files = get_branch_files(folder, up)
                if sha:
                    out[folder] = (up, sha, files)
        except Exception:
            log.exception("git_panel: scan de committed-on-branch falhou")
        self._signals.done.emit(out)


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
    pasta, mais `git diff --numstat` pras ±linhas da árvore. Só devolve
    dados; o rebuild da árvore fica na UI thread."""

    def __init__(
        self,
        epoch: int,
        folders: list[str],
        signals: _StatusScanSignals,
        compare_bases: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.epoch = epoch
        self.folders = folders
        self.signals = signals
        # {folder: base_rev} — presente só quando o modo comparação está
        # ativo; nesses folders o scan troca de fonte (ver run()).
        self.compare_bases = compare_bases or {}

    def run(self) -> None:
        from .. import perf
        statuses: dict[str, GitStatus] = {}
        numstats: dict[str, dict[str, tuple[int, int]]] = {}
        compare_scans: dict[str, CompareScan] = {}
        for folder in self.folders:
            perf.count("git.status.git_panel")
            try:
                # Sempre fresco (o painel reflete ações do usuário na hora),
                # mas publica no cache compartilhado pra sidebar reusar.
                statuses[folder] = get_status_fresh(folder)
            except Exception:
                log.exception("git_panel: get_status falhou em %s", folder)
                statuses[folder] = GitStatus(folder=folder, is_repo=False)
            try:
                numstats[folder] = _collect_numstat(folder)
            except Exception:
                numstats[folder] = {}

            base = self.compare_bases.get(folder)
            if base and statuses[folder].is_repo:
                try:
                    scan = get_compare_scan(folder, base)
                except Exception:
                    log.exception("git_panel: get_compare_scan falhou em %s", folder)
                    scan = CompareScan(folder=folder, base_rev=base, error="falha interna")
                compare_scans[folder] = scan
                if not scan.error:
                    # Substitui a fonte da árvore por "merge-base → working
                    # tree" — mesmo formato (GitStatus.files) pra reusar o
                    # resto do pipeline (_add_repo, fingerprint, etc).
                    st = statuses[folder]
                    st.files = scan.files
                    numstats[folder] = scan.numstat
        self.signals.done.emit(self.epoch, statuses, numstats, compare_scans)


STATUS_COLOR = {
    "modificado": "#d6b95c",
    "mod (idx+ws)": "#d6b95c",
    "adicionado": "#6fbf73",
    "deletado": "#cf6f6f",
    "renomeado": "#6f9fd8",
    "copiado": "#6f9fd8",
    "novo": "#7f7f7f",
}

# Glyph por status do arquivo (mesma cor do texto), renderizado pequeno
# (ver setIconSize da árvore) pra ler como um "dot" estilo Zed.
_STATUS_ICON_NAME = {
    "adicionado": "fa5s.plus",
    "deletado": "fa5s.minus",
    "renomeado": "fa5s.long-arrow-alt-right",
    "copiado": "fa5s.long-arrow-alt-right",
    "novo": "far.circle",
}
_status_icon_cache: dict[tuple[str, str], object] = {}


def _status_icon(label: str, color: str):
    """QIcon do status, cacheado por (label, cor) — qtawesome recria o QIcon
    a cada chamada e isso roda por arquivo em todo rebuild da árvore."""
    key = (label, color)
    icon = _status_icon_cache.get(key)
    if icon is None:
        from .icons import ic

        icon = ic(_STATUS_ICON_NAME.get(label, "fa5s.circle"), color=color)
        _status_icon_cache[key] = icon
    return icon


def _dir_name_key(path: str) -> tuple[str, str]:
    """Chave de ordenação (diretório, basename): arquivos da raiz primeiro,
    depois cada pasta com seus arquivos juntos — ordenar por path puro
    intercalava arquivos da raiz no meio dos separadores de pasta."""
    if "/" in path:
        rel_dir, name = path.rsplit("/", 1)
        return (rel_dir, name)
    return ("", path)

POLL_INTERVAL_MS = 30_000

# UserRole keys
T_GROUP = "group"
T_FILE = "file"
T_REPO = "repo"
T_FOLDER = "folder"  # separador de pasta na lista de arquivos

# Role extra do item de arquivo: tupla (added, removed) pintada pelo
# _ChangesDelegate na borda direita da linha.
_STATS_ROLE = Qt.ItemDataRole.UserRole + 1

# Pastas que o watcher do worktree nunca observa (pesadas/irrelevantes pro
# status) + teto de diretórios pra não estourar o limite de inotify.
_WATCH_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".nuxt", ".idea", ".gradle", "coverage", ".turbo", "vendor",
    ".tox", ".cache", "out", "bin", "obj",
}
_WATCH_DIR_CAP = 1500

def _worktree_watch_dirs(folder: str) -> list[str]:
    """Diretórios do working tree a observar. O QFileSystemWatcher não é
    recursivo, então cada subpasta entra na lista; podamos pastas pesadas
    (_WATCH_SKIP_DIRS) e limitamos a _WATCH_DIR_CAP. inotify num diretório
    reporta create/delete/modify dos arquivos contidos — é o que dispara o
    refresh da árvore quando um arquivo é salvo."""
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


class _ChangesDelegate(QStyledItemDelegate):
    """Delegate da árvore de changes em coluna única (estilo Zed).

    - Separador de pasta (T_FOLDER): caminho completo dimmed, elidido no
      MEIO — o fim do path (mais informativo) fica sempre visível.
    - Demais linhas: fundo/seleção/checkbox/ícone pintados pelo estilo
      nativo (preserva hit-test do checkbox), nome elidido à direita
      parando antes da zona de stats, e '+N -M' (verde/vermelho, dado em
      _STATS_ROLE) colados à margem direita da linha. Linhas sem stats
      usam a largura toda — nenhum pixel fica reservado.
    """

    _ADD = QColor("#6fbf73")
    _DEL = QColor("#cf6f6f")
    _DIM = QColor("#5f5f5f")
    _SEL_TEXT = QColor("#262626")
    _FALLBACK = QColor("#c6c6c6")
    _GAP = 5

    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        full_text = opt.text
        # O estilo pinta fundo/hover/seleção/checkbox/ícone; o texto (que
        # precisa de elide custom) é responsabilidade nossa.
        opt.text = ""
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget
        )

        fm = QFontMetrics(opt.font)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget
        )

        data = index.data(Qt.ItemDataRole.UserRole) or {}
        if isinstance(data, dict) and data.get("type") == T_FOLDER:
            painter.save()
            painter.setFont(opt.font)
            painter.setPen(self._SEL_TEXT if selected else self._DIM)
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter,
                fm.elidedText(
                    full_text, Qt.TextElideMode.ElideMiddle, text_rect.width()
                ),
            )
            painter.restore()
            return

        stats = index.data(_STATS_ROLE)
        add_s = del_s = ""
        if isinstance(stats, tuple) and len(stats) == 2:
            added, removed = stats
            add_s = f"+{added}" if added else ""
            del_s = f"-{removed}" if removed else ""
        stats_w = 0
        if add_s or del_s:
            stats_w = fm.horizontalAdvance(add_s) + fm.horizontalAdvance(del_s)
            if add_s and del_s:
                stats_w += self._GAP

        painter.save()
        painter.setFont(opt.font)
        avail = text_rect.width() - (stats_w + self._GAP if stats_w else 0)
        if selected:
            pen = self._SEL_TEXT
        else:
            fg = index.data(Qt.ItemDataRole.ForegroundRole)
            pen = fg.color() if isinstance(fg, QBrush) else self._FALLBACK
        painter.setPen(pen)
        painter.drawText(
            QRect(
                text_rect.x(), text_rect.y(), max(0, avail), text_rect.height()
            ),
            Qt.AlignmentFlag.AlignVCenter,
            fm.elidedText(full_text, Qt.TextElideMode.ElideRight, max(0, avail)),
        )

        # Stats da direita pra esquerda, colados à margem da LINHA (não do
        # text_rect) pra ficarem alinhados entre arquivos com indentação igual.
        x = opt.rect.right() - 4
        r = opt.rect
        if del_s:
            w = fm.horizontalAdvance(del_s)
            painter.setPen(self._SEL_TEXT if selected else self._DEL)
            painter.drawText(
                QRect(x - w, r.top(), w, r.height()),
                Qt.AlignmentFlag.AlignVCenter,
                del_s,
            )
            x -= w + self._GAP
        if add_s:
            w = fm.horizontalAdvance(add_s)
            painter.setPen(self._SEL_TEXT if selected else self._ADD)
            painter.drawText(
                QRect(x - w, r.top(), w, r.height()),
                Qt.AlignmentFlag.AlignVCenter,
                add_s,
            )
        painter.restore()


class GitPanel(QWidget):
    """Painel de changes (estilo Zed/IntelliJ Commit):
    - QTreeWidget de coluna única com grupos "Changes" e "Unversioned";
      single-repo monta os grupos direto na raiz, multi-repo tem um nível
      de item por repo. Separadores de pasta dimmed + arquivos (basename,
      ícone de status, ±linhas à direita) via _ChangesDelegate.
    - Cada arquivo tem checkbox; o commit usa só os marcados
    - Área de commit no rodapé (mensagem multilinha + botão Commit)
    - Diff inline opcional (toggle no header)
    - Auto-refresh via QFileSystemWatcher + poll a cada 30s
    """

    open_file_requested = Signal(str)
    # Duplo-clique num arquivo modificado: abrir o diff como aba central
    # (folder, rel_path, staged) — estilo Orca.
    open_diff_tab_requested = Signal(str, str, bool)
    # Duplo-clique num arquivo da seção COMMITTED ON BRANCH: diff
    # commitado (folder, rel_path, merge_base_sha) como aba central.
    open_committed_diff_requested = Signal(str, str, str)
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

        # Modo "Comparar com branch base" (estilo IntelliJ "Compare with
        # branch..."): None = mudanças locais (comportamento normal); senão,
        # a árvore lista merge-base(base, HEAD) → working tree, somente
        # leitura. Ver _on_compare_btn_clicked / _apply_statuses.
        self._compare_base: str | None = None
        self._compare_scans: dict[str, CompareScan] = {}
        self._read_only_mode: bool = False

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
            "QSplitter::handle { background: #454545; }"
            "QSplitter::handle:hover { background: #f4f4f4; }"
        )

        self._tree = QTreeWidget()
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(False)
        # Indentação curta: com grupos na raiz (single-repo) sobra largura
        # pro nome do arquivo em painéis estreitos.
        self._tree.setIndentation(11)
        self._tree.setUniformRowHeights(True)
        # Ícones de status pequenos — leem como um "dot" colorido, não como
        # ícone de toolbar.
        from PySide6.QtCore import QSize as _QSize

        self._tree.setIconSize(_QSize(10, 10))
        self._tree.setStyleSheet(
            "QTreeWidget {"
            "  background: #2e2e2e; border: 1px solid #4f4f4f;"
            "  border-radius: 6px; color: #f4f4f4;"
            "}"
            "QTreeWidget::item { padding: 2px 4px; color: #c6c6c6; }"
            "QTreeWidget::item:hover { background: #3a3a3a; color: #fff; }"
            "QTreeWidget::item:selected { background: #f4f4f4; color: #262626; }"
        )
        # Coluna única: o delegate pinta nome elidido + stats "+N -M" na
        # borda direita da própria linha (nada de coluna fixa reservada).
        self._changes_delegate = _ChangesDelegate(self._tree)
        self._tree.setItemDelegate(self._changes_delegate)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemClicked.connect(self._on_single_click)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)

        # Seção CHANGES (estilo Orca): header sm-caps + contador + tree.
        changes_box = QWidget()
        cb_lay = QVBoxLayout(changes_box)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        cb_lay.setSpacing(2)
        changes_hdr = QHBoxLayout()
        changes_hdr.setContentsMargins(4, 0, 4, 0)
        changes_lbl = QLabel("CHANGES")
        changes_lbl.setStyleSheet(theme.section_header_qss())
        changes_hdr.addWidget(changes_lbl)
        changes_hdr.addWidget(self._counter)
        changes_hdr.addStretch()
        cb_lay.addLayout(changes_hdr)
        cb_lay.addWidget(self._tree, stretch=1)
        split.addWidget(changes_box)

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
            "QWidget { background: #313131; border-bottom: 1px solid #454545; }"
            "QPushButton { background: transparent; color: #7f7f7f; border: 1px solid transparent;"
            " border-radius: 3px; padding: 1px 7px; font-size: 11px; }"
            "QPushButton:hover { color: #c6c6c6; border-color: #4f4f4f; }"
            "QPushButton:checked { background: #2e2e2e; color: #f4f4f4; border-color: #f4f4f4; }"
        )
        self._diff_hdr = diff_hdr
        hdr_lay = QHBoxLayout(diff_hdr)
        hdr_lay.setContentsMargins(6, 2, 6, 2)
        hdr_lay.setSpacing(4)

        self._diff_filename = QLabel("")
        self._diff_filename.setStyleSheet("color: #8f8f8f; font-size: 11px; background: transparent;")
        hdr_lay.addWidget(self._diff_filename)
        hdr_lay.addStretch()
        # Duplo-clique no header (widget normal, não o webview) também abre
        # o modal expandido — capturar duplo-clique de dentro do conteúdo
        # renderizado pelo QWebEngineView não é confiável via Qt.
        diff_hdr.installEventFilter(self)
        self._diff_filename.installEventFilter(self)

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
        sep.setStyleSheet("color: #4f4f4f; background: transparent;")
        hdr_lay.addWidget(sep)

        self._diff_ctx_btn = QPushButton("Expandir")
        self._diff_ctx_btn.setCheckable(True)
        self._diff_ctx_btn.setToolTip("Mostrar arquivo completo / só hunks")
        self._diff_ctx_btn.clicked.connect(self._toggle_diff_context)
        hdr_lay.addWidget(self._diff_ctx_btn)

        self._diff_expand_btn = QPushButton("⛶")
        self._diff_expand_btn.setToolTip(
            "Abrir num modal grande, com navegação entre arquivos "
            "(duplo clique aqui também abre)"
        )
        self._diff_expand_btn.clicked.connect(self._open_diff_expand_dialog)
        hdr_lay.addWidget(self._diff_expand_btn)

        diff_vlay.addWidget(diff_hdr)

        self._diff_web = DiffWebView(diff_container)
        diff_vlay.addWidget(self._diff_web, stretch=1)

        self._diff_container = diff_container
        split.addWidget(diff_container)
        split.setSizes([400, 0])
        self._tree_diff_split = split

        # Área de commit
        commit_area = self._build_commit_area()
        self._commit_area = commit_area

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
            "  background: #2c3037; border: 1px solid #4f4f4f;"
            "  border-radius: 6px; color: #c6c6c6; padding: 4px;"
            "}"
        )

        # Splitter vertical maior: tree/diff, área de commit e console de
        # atividade — todos redimensionáveis arrastando os handles. O console
        # fica colapsado (size 0) enquanto oculto.
        main_split = QSplitter(Qt.Orientation.Vertical)
        main_split.setChildrenCollapsible(False)
        main_split.setHandleWidth(6)
        main_split.setStyleSheet(
            "QSplitter::handle { background: #454545; }"
            "QSplitter::handle:hover { background: #f4f4f4; }"
        )
        # Ordem estilo Orca: commit (mensagem + stage) no TOPO, CHANGES no
        # meio, COMMITTED ON BRANCH e atividade embaixo.
        self._committed_box = self._build_committed_section()
        main_split.addWidget(commit_area)
        main_split.addWidget(split)
        main_split.addWidget(self._committed_box)
        main_split.addWidget(self._activity)
        main_split.setStretchFactor(0, 0)  # commit
        main_split.setStretchFactor(1, 1)  # changes/diff
        main_split.setStretchFactor(2, 0)  # committed on branch
        main_split.setStretchFactor(3, 0)  # atividade git
        main_split.setSizes([132, 400, 24, 0])
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
        self._status_spinner = Spinner(parent=self)
        self._status_spinner.tick.connect(self._on_status_spinner_tick)

        # Diretórios do worktree atualmente observados (caros de montar — só
        # recomputados quando o conjunto de repos muda, e em thread do pool).
        self._wt_dirs: list[str] = []
        self._wt_dirs_key: tuple = ()
        self._watch_dirs_signals = _WatchDirsSignals()
        self._watch_dirs_signals.done.connect(self._on_watch_dirs_ready)
        self._committed_signals = _CommittedScanSignals()
        self._committed_signals.done.connect(self._apply_committed)

    # ---------- construção ----------

    def _make_toolbar(self, branch_row: QHBoxLayout, actions_row: QHBoxLayout) -> None:
        """Layout estilo Orca: linha 1 = 'Criar PR' em pill de destaque +
        refresh + menu ⋯ (ações secundárias); linha 2 = branch + compare +
        push. O contador de mudanças vive no header da seção CHANGES."""
        from PySide6.QtCore import QSize as _QS

        from .icons import ic as _ic

        # Branch picker inline — mostra a branch atual (ou "(multi)") com
        # ícone code-branch. Click abre o branch picker do primeiro repo.
        self._branch_btn = QPushButton("  —")
        self._branch_btn.setIcon(_ic("fa5s.code-branch", color="#f4f4f4"))
        self._branch_btn.setIconSize(_QS(11, 11))
        self._branch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._branch_btn.setToolTip("Trocar branch do primeiro repo deste workspace")
        # Branch destacada em amarelo pra ficar visível à primeira vista,
        # tanto em mono-repo quanto em multi-repo.
        self._branch_btn.setStyleSheet(
            "QPushButton { background: rgba(255, 255, 255, 0.06); color: #f4f4f4; "
            "border: 1px solid rgba(255, 255, 255, 0.22); border-radius: 4px; "
            "padding: 2px 8px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { border-color: #f4f4f4; color: #f4f4f4; "
            "background: rgba(255, 255, 255, 0.10); }"
            "QPushButton:disabled { color: #5f5f5f; border-color: #4f4f4f; "
            "background: transparent; font-weight: 400; }"
        )
        self._branch_btn.clicked.connect(self._on_branch_btn_clicked)

        # Toggle do modo "Comparar com branch base" — estilo IntelliJ
        # "Compare with branch...". Azul (não âmbar) pra não se confundir
        # com o badge da branch atual.
        self._compare_btn = QPushButton("  ⇆")
        self._compare_btn.setCheckable(True)
        self._compare_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._compare_btn.setToolTip(
            "Comparar com branch base — mostra tudo que a branch atual "
            "introduz (commitado ou não) em relação a outra branch"
        )
        self._compare_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #7f7f7f; "
            "border: 1px solid transparent; border-radius: 4px; "
            "padding: 2px 8px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { border-color: #6f9fd8; color: #6f9fd8; }"
            "QPushButton:checked { background: rgba(122, 166, 230, 0.14); "
            "color: #6f9fd8; border-color: rgba(122, 166, 230, 0.5); }"
        )
        self._compare_btn.clicked.connect(self._on_compare_btn_clicked)

        # Contador de mudanças — criado aqui, mas exibido no header da
        # seção CHANGES (o __init__ o insere lá).
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #a2a2a2; font-size: 11px; padding: 0 4px;")

        btn_css = (
            "QPushButton { background: transparent; color: #a2a2a2; "
            "border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { color: #d8d8d8; border-color: #f4f4f4; }"
            "QPushButton:disabled { color: #4f4f4f; }"
        )

        def _icon_btn(qta_name: str, tooltip: str, slot, label: str = "") -> QPushButton:
            b = QPushButton(f"  {label}" if label else "")
            b.setIcon(_ic(qta_name, color="#a2a2a2"))
            b.setIconSize(_QS(13, 13))
            b.setToolTip(tooltip)
            b.setStyleSheet(btn_css)
            b.clicked.connect(slot)
            return b

        # ---- Linha 1: Criar PR (destaque, estilo Orca) + refresh + ⋯
        self._pr_btn = QPushButton("  Criar PR")
        self._pr_btn.setIcon(_ic("ph.git-pull-request", color="#1d1d1d"))
        self._pr_btn.setIconSize(_QS(13, 13))
        self._pr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pr_btn.setToolTip(
            "Abrir Pull Request no GitHub (branch atual → base)"
        )
        self._pr_btn.setStyleSheet(theme.primary_button_qss())
        self._pr_btn.clicked.connect(self._do_open_pr)
        branch_row.addWidget(self._pr_btn)
        branch_row.addStretch()
        branch_row.addWidget(_icon_btn("ph.arrow-clockwise", "Atualizar", self.refresh))
        more_btn = QPushButton()
        more_btn.setIcon(_ic("ph.dots-three", color="#a2a2a2"))
        more_btn.setIconSize(_QS(14, 14))
        more_btn.setToolTip("Mais ações (fetch, pull, diff inline, atividade git)")
        more_btn.setStyleSheet(btn_css)
        more_btn.clicked.connect(self._open_more_menu)
        branch_row.addWidget(more_btn)
        self._more_btn = more_btn

        # ---- Linha 2: branch + compare + push
        actions_row.addWidget(self._branch_btn)
        actions_row.addWidget(self._compare_btn)
        actions_row.addStretch()
        actions_row.addWidget(
            _icon_btn(
                "ph.cloud-arrow-up",
                "Push — mostra commits e arquivos antes de enviar",
                self._do_push,
                label="Push",
            )
        )

    def _open_more_menu(self) -> None:
        """Menu ⋯ com as ações secundárias que saíram da toolbar."""
        menu = QMenu(self._more_btn)
        menu.addAction("Fetch (todos os repos)").triggered.connect(
            self._do_fetch_all
        )
        menu.addAction("Pull ff-only (todos os repos)").triggered.connect(
            self._do_pull_all
        )
        menu.addSeparator()
        a_diff = menu.addAction("Painel de diff inline")
        a_diff.setCheckable(True)
        a_diff.setChecked(self._diff_visible)
        a_diff.triggered.connect(lambda _c: self._toggle_diff())
        a_log = menu.addAction("Console de atividade git")
        a_log.setCheckable(True)
        a_log.setChecked(self._activity.isVisible())
        a_log.triggered.connect(lambda _c: self._toggle_activity())
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

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
            "  background: #2e2e2e; border: 1px solid #4f4f4f;"
            "  border-radius: 4px; color: #f4f4f4; padding: 4px;"
            "}"
            "QPlainTextEdit:focus { border-color: #f4f4f4; }"
        )
        v.addWidget(self._msg, stretch=1)

        # Stage All largo (estilo Orca) — marca/desmarca todos os arquivos
        # da seção CHANGES pro commit.
        self._stage_all_btn = QPushButton("+ Marcar tudo pro commit")
        self._stage_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stage_all_btn.setToolTip(
            "Marca todos os arquivos de CHANGES (clique direito: desmarcar todos)"
        )
        self._stage_all_btn.setStyleSheet(
            "QPushButton { background: #383838; color: #c6c6c6;"
            " border: 1px solid #4f4f4f; border-radius: 6px; padding: 5px 10px; }"
            "QPushButton:hover { border-color: #7f7f7f; color: #f4f4f4; }"
        )
        self._stage_all_btn.clicked.connect(
            lambda: self._set_all_files_checked(True)
        )
        self._stage_all_btn.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._stage_all_btn.customContextMenuRequested.connect(
            lambda _p: self._set_all_files_checked(False)
        )
        v.addWidget(self._stage_all_btn)

        bottom = QHBoxLayout()
        bottom.setSpacing(4)

        primary_qss = (
            "QPushButton {"
            "  background: #f4f4f4; color: #262626;"
            "  border: 0; border-radius: 4px; padding: 4px 14px; font-weight: 600;"
            "}"
            "QPushButton:hover { background: #ffffff; }"
            "QPushButton:disabled { background: #454545; color: #5f5f5f; }"
        )
        ghost_qss = (
            "QPushButton {"
            "  background: #383838; color: #c6c6c6;"
            "  border: 1px solid #4f4f4f; border-radius: 4px;"
            "  padding: 4px 12px;"
            "}"
            "QPushButton:hover { border-color: #f4f4f4; color: #d8d8d8; }"
            "QPushButton:disabled { color: #5f5f5f; border-color: #454545; }"
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

    def _set_all_files_checked(self, checked: bool) -> None:
        """Marca/desmarca todos os arquivos de CHANGES pro commit
        (equivalente ao Stage All do Orca)."""
        if self._read_only_mode:
            return
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        def _walk(item: QTreeWidgetItem) -> None:
            for i in range(item.childCount()):
                child = item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get("type") == T_FILE and (
                    child.flags() & Qt.ItemFlag.ItemIsUserCheckable
                ):
                    child.setCheckState(0, state)
                _walk(child)
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            data = top.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE and (
                top.flags() & Qt.ItemFlag.ItemIsUserCheckable
            ):
                top.setCheckState(0, state)
            _walk(top)

    # ---------- COMMITTED ON BRANCH (estilo Orca) ----------

    def _build_committed_section(self) -> QWidget:
        """Seção colapsável com os arquivos já COMMITADOS na branch
        (merge-base(upstream)..HEAD). Carrega lazy na primeira expansão."""
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        hdr = QPushButton("  COMMITTED ON BRANCH")
        hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.setCheckable(True)
        hdr.setStyleSheet(
            "QPushButton { background: transparent; color: #7f7f7f;"
            " border: 0; text-align: left; font-size: 11px;"
            " font-weight: 600; letter-spacing: 0.5px; padding: 3px 4px; }"
            "QPushButton:hover { color: #c6c6c6; }"
            "QPushButton:checked { color: #c6c6c6; }"
        )
        hdr.toggled.connect(self._on_committed_toggled)
        self._committed_hdr = hdr
        v.addWidget(hdr)

        tree = QTreeWidget()
        tree.setColumnCount(1)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setIndentation(11)
        tree.setUniformRowHeights(True)
        tree.setStyleSheet(self._tree.styleSheet())
        tree.setItemDelegate(_ChangesDelegate(tree))
        tree.setVisible(False)
        tree.itemDoubleClicked.connect(self._on_committed_double_click)
        self._committed_tree = tree
        v.addWidget(tree, stretch=1)
        # merge_base por folder — usado no diff do duplo-clique.
        self._committed_bases: dict[str, str] = {}
        self._committed_loaded = False
        return box

    def _on_committed_toggled(self, checked: bool) -> None:
        self._committed_tree.setVisible(checked)
        if checked:
            # Dá altura útil pra seção dentro do splitter.
            sizes = self._main_split.sizes()
            if len(sizes) == 4 and sizes[2] < 120:
                total = sum(sizes)
                sizes[2] = min(220, max(140, total // 4))
                sizes[1] = max(120, sizes[1] - sizes[2])
                self._main_split.setSizes(sizes)
            self._load_committed()
        else:
            self._committed_loaded = False  # re-scan na próxima expansão

    def _load_committed(self) -> None:
        """Escaneia (thread pool) os arquivos commitados vs upstream de
        cada repo ativo e popula a tree da seção."""
        if self._committed_loaded:
            return
        self._committed_loaded = True
        folders = [f for f, st in self._statuses.items() if st.is_repo]
        if not folders:
            self._committed_hdr.setText("  COMMITTED ON BRANCH — sem repo")
            return
        self._committed_hdr.setText("  COMMITTED ON BRANCH — carregando…")
        self._status_pool.start(
            _CommittedScanTask(folders, self._committed_signals)
        )

    def _apply_committed(self, result: dict) -> None:
        tree = self._committed_tree
        tree.clear()
        self._committed_bases = {}
        total = 0
        for folder, (up, sha, files) in result.items():
            self._committed_bases[folder] = sha
            parent: QTreeWidgetItem | None = None
            if len(result) > 1:
                parent = QTreeWidgetItem(tree, [Path(folder).name])
                parent.setForeground(0, QColor("#7f7f7f"))
                parent.setExpanded(True)
            for bf in files:
                total += 1
                item = QTreeWidgetItem([bf.path.rsplit("/", 1)[-1]])
                item.setToolTip(0, f"{bf.path} ({bf.status}) — vs {up}")
                item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"folder": folder, "rel_path": bf.path},
                )
                item.setData(0, _STATS_ROLE, (bf.plus, bf.minus))
                if parent is not None:
                    parent.addChild(item)
                else:
                    tree.addTopLevelItem(item)
        self._committed_hdr.setText(
            f"  COMMITTED ON BRANCH {total}" if total
            else "  COMMITTED ON BRANCH — nada além do upstream"
        )

    def _on_committed_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        folder = data.get("folder")
        rel = data.get("rel_path")
        sha = self._committed_bases.get(folder or "")
        if folder and rel and sha:
            self.open_committed_diff_requested.emit(folder, rel, sha)

    # ---------- workspace ----------

    def set_workspace(self, workspace: Workspace | None) -> None:
        self.workspace = workspace
        # Debounce curto: na troca de workspace este método pode ser
        # chamado junto com set_folders_override (sync do console ativo) —
        # coalesce num único refresh em vez de dois scans de git status.
        self._refresh_timer.start(50)

    def set_folders_override(self, folders: list[str] | None) -> None:
        """Faz o painel inspecionar `folders` (ex.: worktree do console ativo)
        em vez de workspace.folders. None volta ao comportamento do workspace."""
        new = list(folders) if folders is not None else None
        if new == self._folders_override:
            return
        self._folders_override = new
        self._refresh_timer.start(50)

    def _active_folders(self) -> list[str]:
        """Pastas a inspecionar: override do console ativo, senão as do workspace."""
        if self._folders_override is not None:
            return self._folders_override
        if self.workspace and self.workspace.folders:
            return list(self.workspace.folders)
        return []

    def has_any_repo(self) -> bool:
        return self._has_any_repo

    # ---------- modo comparação ----------

    def _on_compare_btn_clicked(self) -> None:
        if self._compare_base is not None:
            # Já ativo: menu rápido pra trocar de base ou voltar ao normal
            # (em vez de só desligar — evita 2 cliques pra trocar de base).
            menu = QMenu(self)
            menu.addAction(self._action("Trocar base…", self._pick_compare_base))
            menu.addAction(
                self._action("Voltar a mudanças locais", self._disable_compare_mode)
            )
            self._compare_btn.setChecked(True)
            menu.exec_(
                self._compare_btn.mapToGlobal(
                    self._compare_btn.rect().bottomLeft()
                )
            )
            return
        if not self._pick_compare_base():
            self._compare_btn.setChecked(False)

    def _pick_compare_base(self) -> bool:
        """Abre o picker de branch (com remotas) pra escolher a base de
        comparação. True se o usuário escolheu uma branch."""
        repo_folders = [f for f, s in self._statuses.items() if s.is_repo]
        if not repo_folders:
            repo_folders = [f for f in self._active_folders()]
        if not repo_folders:
            QMessageBox.information(
                self, "Comparar com branch base", "Nenhum repositório git aqui."
            )
            return False
        first = repo_folders[0]
        branches, current = list_branches(first, include_remotes=True)
        if not branches:
            QMessageBox.information(
                self, "Comparar com branch base",
                f"{Path(first).name}: sem branches.",
            )
            return False
        suggestion = compare_meta.get_compare_base(first)
        from .branch_picker_dialog import BranchPickerDialog

        dlg = BranchPickerDialog(
            branches, suggestion or current, f"comparar {Path(first).name}", self
        )
        if dlg.exec() != dlg.DialogCode.Accepted or not dlg.selected_branch:
            return False
        base = dlg.selected_branch
        self._compare_base = base
        self._compare_btn.setChecked(True)
        for folder in repo_folders:
            compare_meta.set_compare_base(folder, base)
        self.refresh()
        return True

    def _disable_compare_mode(self) -> None:
        self._compare_base = None
        self._compare_scans = {}
        self._compare_btn.setChecked(False)
        self.refresh()

    def _set_read_only_mode(self, read_only: bool) -> None:
        """Modo comparação é somente leitura: esconde a área de commit (não
        faz sentido commitar 'vs base') e libera o espaço pro diff/árvore.
        Índices do _main_split: 0=tree/diff, 1=commit, 2=atividade."""
        if getattr(self, "_read_only_mode", False) == read_only:
            return
        self._read_only_mode = read_only
        self._commit_area.setVisible(not read_only)
        sizes = self._main_split.sizes()
        if len(sizes) == 3:
            if read_only and sizes[1] > 0:
                sizes[0] += sizes[1]
                sizes[1] = 0
            elif not read_only and sizes[1] == 0:
                take = max(90, sizes[0] // 4)
                sizes[0] = max(120, sizes[0] - take)
                sizes[1] = take
            self._main_split.setSizes(sizes)

    # ---------- refresh ----------

    def _schedule_refresh(self, *_args) -> None:
        # Intervalo EXPLÍCITO: QTimer.start(ms) muda o interval do timer
        # permanentemente, então o start(50) da troca de workspace estava
        # rebaixando este debounce de 400ms pra 50ms — o watcher passava a
        # disparar um scan de git a cada rajada de escrita de arquivo
        # (ex.: Claude trabalhando) e o app inteiro sentia.
        self._refresh_timer.start(400)

    def refresh(self) -> None:
        # Drena reflogs antes de qualquer early-return — captura atividade
        # (merge/commit/checkout/pull) de qualquer origem, inclusive skills.
        # Barato (stat/read de arquivo), fica síncrono.
        self._drain_reflogs()

        # Preserva o estado de checked dos arquivos (rel_path) por repo —
        # lido da árvore atual (UI thread) pra reaplicar no rebuild. Walk
        # genérico: funciona tanto com grupos na raiz (single-repo flat)
        # quanto com nível de repo (multi-repo).
        self._prev_unchecked = {}
        self._collect_unchecked_files(
            self._tree.invisibleRootItem(), self._prev_unchecked
        )

        active_folders = self._active_folders()
        self._status_epoch += 1
        if not active_folders:
            # Sem pastas → aplica direto, sem thread.
            self._status_spinner.stop()
            self._apply_statuses(self._status_epoch, {}, {}, {})
            return

        # Coleta `get_status` (subprocess) numa thread — não bloqueia a UI.
        # Mostra "atualizando…" no contador enquanto roda; _apply_statuses
        # sempre recalcula o texto final via _update_summary_labels.
        self._counter.setText(f"{self._status_spinner.frame()} atualizando…")
        self._status_spinner.start()
        compare_bases = (
            {f: self._compare_base for f in active_folders}
            if self._compare_base
            else None
        )
        self._status_pool.start(
            _StatusScanTask(
                self._status_epoch, list(active_folders), self._status_signals,
                compare_bases=compare_bases,
            )
        )

    def _on_status_spinner_tick(self, frame: str) -> None:
        self._counter.setText(f"{frame} atualizando…")

    def _apply_statuses(
        self, epoch: int, new_statuses: dict, numstats: dict, compare_scans: dict | None = None,
    ) -> None:
        # Descarta scan obsoleto (override/seleção mudou no meio do caminho).
        if epoch != self._status_epoch:
            return
        self._status_spinner.stop()
        prev_unchecked = self._prev_unchecked
        active_folders = self._active_folders()
        self._compare_scans = compare_scans or {}
        self._set_read_only_mode(bool(self._compare_base))

        # Refresh ao vivo do diff exibido — roda ANTES do early-return de
        # fingerprint porque o diff pode mudar sem alterar a lista de arquivos
        # (ex.: editar de novo um arquivo já "M").
        self._refresh_shown_diff(new_statuses)

        # Coleta primeiro, decide depois: se nada mudou desde o último
        # refresh, evita rebuild da árvore (preserva scroll/seleção e zera
        # custo de paint do QTreeWidget). Fingerprint = tuple imutável das
        # infos visíveis por repo; inclui a base de comparação pra forçar
        # rebuild ao trocar de modo/base mesmo com lista de arquivos igual.
        new_fp = (_fingerprint_statuses(new_statuses), self._compare_base)
        if new_fp == self._status_fingerprint and self._tree.topLevelItemCount():
            # Lista de arquivos idêntica — sem rebuild (preserva scroll e
            # seleção), mas os ±linhas podem ter mudado (ex.: salvar de novo
            # um arquivo já "M"): atualiza stats in-place e o resumo.
            self._statuses = new_statuses
            self._update_stats_in_place(numstats or {})
            self._update_summary_labels(numstats)
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

        # Single-repo (caso comum) monta os grupos direto na raiz — sem o
        # nível do item de repo, que só come indentação/largura; a branch já
        # aparece na toolbar e no header do painel.
        repo_count = sum(
            1 for f in active_folders if self._statuses[f].is_repo
        )
        repo_folders: list[str] = []
        for folder in active_folders:
            status = self._statuses[folder]
            if not status.is_repo:
                continue
            repo_folders.append(folder)
            self._add_repo(
                folder, status,
                prev_unchecked.get(folder, set()),
                numstats.get(folder) if numstats else None,
                flat=(repo_count == 1),
            )

        self._has_any_repo = bool(repo_folders)
        self._update_summary_labels(numstats)
        if not self._has_any_repo:
            placeholder = QTreeWidgetItem(["(nenhuma pasta é repo git)"])
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(placeholder)
            self._poll_timer.stop()
        elif not self._poll_timer.isActive():
            self._poll_timer.start()

        self._tree.blockSignals(False)
        self._update_watches(repo_folders)
        self._update_commit_button()

    def _update_summary_labels(self, numstats: dict | None) -> None:
        """Contador da toolbar ("● N arquivo(s) +X -Y"), badge da branch e
        resumo pro header do painel. Recalculado a cada scan — inclusive no
        early-return de fingerprint, pros ±linhas ficarem ao vivo."""
        repo_stats = [st for st in self._statuses.values() if st.is_repo]
        if not repo_stats:
            self._counter.setText("")
            self._branch_btn.setText("  —")
            self._branch_btn.setEnabled(False)
            self.header_summary_changed.emit("")
            return

        total_files = sum(len(st.files) for st in repo_stats)
        total_add = total_del = 0
        for folder, st in self._statuses.items():
            if not st.is_repo:
                continue
            ns = (numstats or {}).get(folder) or {}
            total_add += sum(a for a, _ in ns.values())
            total_del += sum(d for _, d in ns.values())
        stats_html = ""
        if total_add or total_del:
            stats_html = (
                f"  <span style='color:#6fbf73'>+{total_add}</span> "
                f"<span style='color:#cf6f6f'>-{total_del}</span>"
            )

        if self._compare_base:
            base_label = self._compare_base[:24]
            self._counter.setText(
                f"<span style='color:#6f9fd8'>⇆ {total_files} arquivo(s) "
                f"vs {base_label}</span>{stats_html}"
            )
        elif total_files == 0:
            self._counter.setText("<span style='color:#6fbf73'>✓ limpo</span>")
        else:
            self._counter.setText(
                f"<span style='color:#f4f4f4'>● {total_files} arquivo(s)</span>"
                f"{stats_html}"
            )
        self._counter.setTextFormat(Qt.TextFormat.RichText)

        # Atualiza label do branch picker: 1 repo → mostra branch;
        # >1 repos com mesma branch → idem; senão → "(multi)".
        branches = {s.branch for s in repo_stats if s.branch}
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

        # Resumo pro header do painel: "⎇ branch · N mudança(s) +X -Y" ou
        # "⎇ branch · ✓ limpo". Cores espelham o toolbar.
        if branch_text:
            br_html = (
                f"<span style='color:{theme.WARNING}'>⎇ {branch_text[:24]}</span>"
            )
            if self._compare_base:
                self.header_summary_changed.emit(
                    f"{br_html} <span style='color:{theme.TEXT_FAINT}'>·</span> "
                    f"<span style='color:#6f9fd8'>⇆ {total_files} vs "
                    f"{self._compare_base[:24]}</span>"
                )
            elif total_files == 0:
                self.header_summary_changed.emit(
                    f"{br_html} <span style='color:{theme.TEXT_FAINT}'>·</span> "
                    f"<span style='color:{theme.SUCCESS}'>✓ limpo</span>"
                )
            else:
                self.header_summary_changed.emit(
                    f"{br_html} <span style='color:{theme.TEXT_FAINT}'>·</span> "
                    f"<span style='color:{theme.WARNING}'>● {total_files} "
                    f"mudança(s)</span>{stats_html}"
                )
        else:
            self.header_summary_changed.emit("")

    def _update_stats_in_place(self, numstats: dict) -> None:
        """Reaplica os ±linhas (_STATS_ROLE) nos itens de arquivo já montados,
        sem rebuild — usado quando o fingerprint não mudou mas o conteúdo dos
        arquivos sim (a lista é igual, os numstats não)."""
        self._tree.blockSignals(True)

        def walk(parent: QTreeWidgetItem) -> None:
            for i in range(parent.childCount()):
                child = parent.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole) or {}
                if data.get("type") == T_FILE:
                    ns = numstats.get(data["folder"]) or {}
                    added, removed = ns.get(data["rel_path"], (0, 0))
                    child.setData(
                        0,
                        _STATS_ROLE,
                        (added, removed) if (added or removed) else None,
                    )
                else:
                    walk(child)

        walk(self._tree.invisibleRootItem())
        self._tree.blockSignals(False)
        self._tree.viewport().update()

    def _collect_unchecked_files(
        self, parent: QTreeWidgetItem, out: dict[str, set[str]]
    ) -> None:
        """Coleta os arquivos desmarcados agrupados por folder — walk
        genérico que funciona com ou sem o nível de item de repo."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Unchecked:
                    out.setdefault(data["folder"], set()).add(data["rel_path"])
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
        # Índices do _main_split: 0=tree/diff, 1=commit, 2=atividade.
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
            f"<span style='color:#5f5f5f'>{ts}</span> "
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
            "merge": "#6f9fd8",
            "pull": "#6f9fd8",
            "rebase": "#6f9fd8",
            "commit": theme.SUCCESS if hasattr(theme, "SUCCESS") else "#6fbf73",
            "checkout": "#d6b95c",
            "reset": "#cf6f6f",
            "revert": "#cf6f6f",
            "cherry-pick": "#6f9fd8",
            "clone": "#6fbf73",
        }.get(action, "#a2a2a2")
        return (f"⎇ {repo}: {msg}  ({new_sha})", color)

    # ---------- árvore ----------

    def _add_repo(
        self,
        folder: str,
        status: GitStatus,
        prev_unchecked: set[str],
        numstats: dict[str, tuple[int, int]] | None = None,
        flat: bool = False,
    ) -> None:
        """Monta os itens de um repo. Com `flat=True` (single-repo, caso
        comum) os grupos vão direto na raiz da árvore — sem o item de repo,
        que só consome indentação; branch/↑↓ já aparecem na toolbar."""
        ns = numstats or {}
        compare_scan = self._compare_scans.get(folder)
        errors: list[str] = []
        if status.error:
            errors.append(status.error)
        if compare_scan and compare_scan.error:
            errors.append(
                f"comparar vs {compare_scan.base_rev}: {compare_scan.error}"
            )

        repo_item: QTreeWidgetItem | None = None
        if not flat:
            name = Path(folder).name
            ahead_behind = ""
            if status.ahead or status.behind:
                bits = []
                if status.ahead:
                    bits.append(f"↑{status.ahead}")
                if status.behind:
                    bits.append(f"↓{status.behind}")
                ahead_behind = " " + "".join(bits)
            marker = (
                "✓ limpo" if not status.files else f"{len(status.files)} mudança(s)"
            )
            # Totais +/- para o label do repo
            total_add = sum(a for a, _ in ns.values())
            total_del = sum(d for _, d in ns.values())
            stats_str = ""
            if total_add:
                stats_str += f"  +{total_add}"
            if total_del:
                stats_str += f"  -{total_del}"
            repo_item = QTreeWidgetItem(
                [f"{name}  ·  {status.branch}{ahead_behind}  ·  {marker}{stats_str}"]
            )
            repo_item.setData(
                0, Qt.ItemDataRole.UserRole, {"type": T_REPO, "folder": folder}
            )
            f = repo_item.font(0)
            f.setBold(True)
            repo_item.setFont(0, f)
            if errors:
                repo_item.setForeground(0, QBrush(QColor("#cf6f6f")))
                repo_item.setText(
                    0, repo_item.text(0) + "  (" + "; ".join(errors) + ")"
                )
            repo_item.setToolTip(0, repo_item.text(0))
        elif errors:
            # Flat sem linha de repo: o erro vira um item próprio no topo.
            err_item = QTreeWidgetItem(["⚠ " + "; ".join(errors)])
            err_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            err_item.setForeground(0, QBrush(QColor("#cf6f6f")))
            err_item.setToolTip(0, "; ".join(errors))
            self._tree.addTopLevelItem(err_item)

        def attach(item: QTreeWidgetItem) -> None:
            if repo_item is not None:
                repo_item.addChild(item)
            else:
                self._tree.addTopLevelItem(item)

        checkable = not self._compare_base
        changes_label = (
            f"Changes vs {self._compare_base}" if self._compare_base else "Changes"
        )

        # Agrupar em Changes / Unversioned
        changes: list[GitFile] = []
        untracked: list[GitFile] = []
        for gf in status.files:
            if gf.is_untracked:
                untracked.append(gf)
            else:
                changes.append(gf)

        if changes:
            grp = self._make_group_item(
                folder, changes_label, len(changes), checkable=checkable
            )
            attach(grp)
            self._add_files_with_dirs(
                grp, folder, changes, prev_unchecked, ns, checkable=checkable
            )
            grp.setExpanded(True)
        if untracked:
            grp = self._make_group_item(
                folder, "Unversioned Files", len(untracked), checkable=checkable
            )
            attach(grp)
            self._add_files_with_dirs(
                grp, folder, untracked, prev_unchecked, ns, checkable=checkable
            )
            grp.setExpanded(True)

        if repo_item is not None:
            repo_item.setExpanded(True)
            self._tree.addTopLevelItem(repo_item)

    def _add_files_with_dirs(
        self,
        parent: QTreeWidgetItem,
        folder: str,
        files: list[GitFile],
        prev_unchecked: set[str],
        numstats: dict[str, tuple[int, int]],
        checkable: bool = True,
    ) -> None:
        """Insere arquivos agrupados por pasta (separadores de diretório dimmed)."""
        # Raiz primeiro, depois por pasta — mesma ordem do _build_diff_entries
        sorted_files = sorted(files, key=lambda gf: _dir_name_key(gf.path))
        last_dir = None
        for gf in sorted_files:
            rel_dir = gf.path.rsplit("/", 1)[0] if "/" in gf.path else ""
            if rel_dir != last_dir:
                last_dir = rel_dir
                if rel_dir:
                    sep = self._make_folder_sep(rel_dir)
                    parent.addChild(sep)
            child = self._make_file_item(
                folder, gf, prev_unchecked, numstats, checkable=checkable
            )
            parent.addChild(child)

    def _make_folder_sep(self, rel_dir: str) -> QTreeWidgetItem:
        """Linha separadora de pasta — dimmed, não selecionável, sem checkbox.
        Guarda o caminho completo; o elide (no meio) é do _ChangesDelegate."""
        item = QTreeWidgetItem([rel_dir])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # não selecionável nem editável
        item.setForeground(0, QBrush(QColor("#5f5f5f")))
        f = item.font(0)
        f.setFamily("monospace")
        f.setPointSizeF(f.pointSizeF() * 0.9)
        item.setFont(0, f)
        item.setToolTip(0, rel_dir)
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": T_FOLDER})
        return item

    def _make_group_item(
        self, folder: str, name: str, count: int, checkable: bool = True
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"{name}  ({count})"])
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        item.setForeground(0, QBrush(QColor("#c6c6c6")))
        if checkable:
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
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
        checkable: bool = True,
    ) -> QTreeWidgetItem:
        rel = gf.path
        # Só o basename — o diretório pai é exibido pelo separador acima
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        color = STATUS_COLOR.get(gf.label(), "#a2a2a2")
        item = QTreeWidgetItem([name])
        item.setForeground(0, QBrush(QColor(color)))
        item.setIcon(0, _status_icon(gf.label(), color))
        mono = item.font(0)
        mono.setFamily("monospace")
        item.setFont(0, mono)
        if checkable:
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
        # Stats +/- pintados pelo _ChangesDelegate na borda direita da linha
        if numstats:
            added, removed = numstats.get(rel, (0, 0))
            if added or removed:
                item.setData(0, _STATS_ROLE, (added, removed))
        return item

    # ---------- interação ----------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (nome exigido pelo Qt)
        if (
            event.type() == QEvent.Type.MouseButtonDblClick
            and obj in (self._diff_hdr, self._diff_filename)
        ):
            self._open_diff_expand_dialog()
            return True
        return super().eventFilter(obj, event)

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
        self._render_shown_diff()

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("type") != T_FILE:
            return
        if self._compare_base:
            # Modo comparação: abre o diff nativo side-by-side (estilo
            # IntelliJ) posicionado no arquivo clicado, comparando contra o
            # merge-base — `file_blob` aceita qualquer rev, incluindo o
            # sentinela WORKTREE pro lado direito (não commitado).
            self._open_compare_diff_viewer(data["folder"], data["rel_path"])
            return
        # Estilo Orca: duplo-clique abre o DIFF do arquivo como aba no
        # painel central (o arquivo em si continua acessível pelo painel
        # Arquivos / menu de contexto).
        self.open_diff_tab_requested.emit(
            data["folder"], data["rel_path"], bool(data.get("staged", False))
        )

    def _open_compare_diff_viewer(self, clicked_folder: str, clicked_rel: str) -> None:
        entries: list[dict] = []
        clicked_index = 0
        for folder, st in self._statuses.items():
            scan = self._compare_scans.get(folder)
            if not st.is_repo or not st.files or not scan or not scan.merge_base_sha:
                continue
            for gf in sorted(st.files, key=lambda f: _dir_name_key(f.path)):
                if folder == clicked_folder and gf.path == clicked_rel:
                    clicked_index = len(entries)
                entries.append(
                    {
                        "folder": folder,
                        "base": scan.merge_base_sha,
                        "head": WORKTREE,
                        "path": gf.path,
                    }
                )
        if not entries:
            return
        from .diff_viewer_dialog import DiffViewerDialog

        DiffViewerDialog(entries, index=clicked_index, parent=self).exec()

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
                self._render_shown_diff()
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
            self._render_shown_diff()

    def _render_shown_diff(self) -> None:
        """Renderiza `self._shown_diff` no pane embutido — modo local usa
        `get_diff` (working tree vs HEAD/index); modo comparação usa
        `get_diff_range` contra o merge-base já calculado pro repo."""
        if self._shown_diff is None:
            return
        folder, rel, staged = self._shown_diff
        name = rel.rsplit("/", 1)[-1] if "/" in rel else rel
        scan = self._compare_scans.get(folder)
        if self._compare_base and scan and scan.merge_base_sha:
            text = get_diff_range(
                folder, rel, scan.merge_base_sha, context=self._diff_context
            )
            self._diff_filename.setText(f"{rel}  ⇆ vs {self._compare_base}")
        else:
            text = get_diff(folder, rel, staged=staged, context=self._diff_context)
            self._diff_filename.setText(rel)
        self._diff_web.show_diff(text, name)

    # ---------- modal expandido (mais espaço + navegação entre arquivos) ----

    def _build_diff_entries(self) -> tuple[list[dict], int]:
        """Monta a lista de arquivos na MESMA ordem da árvore (por repo →
        Changes → Unversioned, cada grupo ordenado por path), no formato
        esperado pelo `DiffExpandDialog`. Devolve (entries, index) com index
        apontando pro arquivo de `self._shown_diff`."""
        entries: list[dict] = []
        shown_key = self._shown_diff[:2] if self._shown_diff else None
        index = 0
        for folder, st in self._statuses.items():
            if not st.is_repo or not st.files:
                continue
            scan = self._compare_scans.get(folder)
            merge_base_sha = (
                scan.merge_base_sha
                if self._compare_base and scan and scan.merge_base_sha
                else ""
            )
            label_suffix = f"⇆ vs {self._compare_base}" if merge_base_sha else ""
            changes = sorted(
                (gf for gf in st.files if not gf.is_untracked),
                key=lambda f: _dir_name_key(f.path),
            )
            untracked = sorted(
                (gf for gf in st.files if gf.is_untracked),
                key=lambda f: _dir_name_key(f.path),
            )
            for gf in (*changes, *untracked):
                if shown_key == (folder, gf.path):
                    index = len(entries)
                entries.append(
                    {
                        "folder": folder,
                        "rel_path": gf.path,
                        "staged": gf.is_staged and not gf.is_unstaged,
                        "merge_base_sha": merge_base_sha,
                        "label_suffix": label_suffix,
                    }
                )
        return entries, index

    def _open_diff_expand_dialog(self) -> None:
        if self._shown_diff is None:
            return
        entries, index = self._build_diff_entries()
        if not entries:
            return
        from .diff_expand_dialog import DiffExpandDialog

        fmt = "side-by-side" if self._diff_side_btn.isChecked() else "line-by-line"
        DiffExpandDialog(
            entries, index=index, output_format=fmt, context=self._diff_context,
            parent=self,
        ).show()

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
        self._render_shown_diff()

    # ---------- collecting checked files ----------

    def _collect_checked_files(self) -> dict[str, list[str]]:
        """Devolve {folder: [rel_path, ...]} pra cada repo com arquivos
        marcados. Walk genérico a partir da raiz — o bucket por folder vem
        do payload de cada arquivo, então funciona com ou sem item de repo."""
        out: dict[str, list[str]] = {}
        self._walk_collect_checked(self._tree.invisibleRootItem(), out)
        return out

    def _walk_collect_checked(
        self, parent: QTreeWidgetItem, out: dict[str, list[str]]
    ) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("type") == T_FILE:
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.setdefault(data["folder"], []).append(data["rel_path"])
            else:
                self._walk_collect_checked(child, out)

    def _update_commit_button(self) -> None:
        if self._compare_base:
            # Modo comparação é somente leitura — a área de commit está
            # escondida (_set_read_only_mode); nada a fazer aqui.
            return
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

        # Modo comparação é somente leitura — sem stage/unstage/rollback/delete.
        if self._compare_base:
            return

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
        # Modo comparação: grupos não têm checkbox nem sentido de stage.
        if self._compare_base:
            return
        group_name = items[0].data(0, Qt.ItemDataRole.UserRole).get("name", "")
        folder = items[0].data(0, Qt.ItemDataRole.UserRole).get("folder", "")
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
        # No modo flat (single-repo) a linha de repo não existe — as ações
        # de repo ficam acessíveis pelo grupo.
        if folder:
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
        if not self._compare_base:
            menu.addSeparator()
            menu.addAction(
                self._action(
                    "+ Stage tudo", lambda: stage_all(folder) and self.refresh()
                )
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
