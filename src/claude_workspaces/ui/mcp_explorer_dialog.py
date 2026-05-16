"""Explorer dos MCP servers do Claude — user + projeto.

Mostra cada servidor com seu transporte, comando/URL, args e
ENV keys (sem valores). Clicar abre o arquivo source no editor.
"""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..errors import LaunchError
from ..models import Workspace
from ..services.mcp_inspector import McpServerEntry, list_servers, mask_sensitive
from ..services.system_open import open_in_file_manager

log = logging.getLogger(__name__)

_SCOPE_COLOR = {"user": "#6aa9e0", "project": "#5ac35a"}
_TRANSPORT_COLOR = {"stdio": "#b08cd6", "sse": "#5ac35a", "http": "#e6a23c"}


class McpExplorerDialog(QDialog):
    def __init__(
        self, workspace: Workspace | None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Explorer de MCP Servers")
        self.resize(900, 600)
        self.workspace = workspace

        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        hint = QLabel(
            "MCP servers extendem o Claude com tools e resources. "
            "Configurados em <code>~/.claude.json</code> (user) e "
            "<code>.mcp.json</code> (projeto)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b0b0b0;")
        outer.addWidget(hint)

        # Split horizontal: lista esquerda, detalhe direita
        body = QHBoxLayout()
        body.setSpacing(8)

        left = QVBoxLayout()
        left.setSpacing(4)
        self._list = QListWidget()
        self._list.setMaximumWidth(280)
        self._list.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 6px; color: #e6e6e6; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #232323; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._list.itemSelectionChanged.connect(self._render_detail)
        left.addWidget(self._list, stretch=1)
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        left.addWidget(self._counter)
        body.addLayout(left)

        # Detalhe
        self._detail_scroll = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_scroll)
        self._detail_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_layout.setSpacing(10)
        body.addWidget(self._detail_scroll, stretch=1)

        outer.addLayout(body, stretch=1)

        # Footer
        buttons = QDialogButtonBox()
        open_user_btn = QPushButton("Abrir ~/.claude.json")
        open_user_btn.clicked.connect(self._open_user_config)
        buttons.addButton(open_user_btn, QDialogButtonBox.ButtonRole.ActionRole)
        if workspace and workspace.folders:
            open_proj_btn = QPushButton("Abrir .mcp.json (projeto)")
            open_proj_btn.clicked.connect(self._open_project_config)
            buttons.addButton(open_proj_btn, QDialogButtonBox.ButtonRole.ActionRole)
        refresh_btn = QPushButton("↻ Recarregar")
        refresh_btn.clicked.connect(self.refresh)
        buttons.addButton(refresh_btn, QDialogButtonBox.ButtonRole.ActionRole)
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.accept)
        outer.addWidget(buttons)

        self._servers: list[McpServerEntry] = []
        self.refresh()

    def refresh(self) -> None:
        folders = self.workspace.folders if self.workspace else None
        try:
            self._servers = list_servers(folders)
        except Exception:
            log.exception("Falha listando MCP servers")
            self._servers = []

        self._list.clear()
        for s in self._servers:
            li = QListWidgetItem(f"{s.name}  ·  {s.transport}")
            li.setData(Qt.ItemDataRole.UserRole, s)
            li.setToolTip(f"Escopo: {s.scope}\nArquivo: {s.source_file}")
            li.setForeground(QBrush(QColor(_SCOPE_COLOR.get(s.scope, "#c8c8c8"))))
            self._list.addItem(li)

        self._counter.setText(f"{len(self._servers)} server(s)")
        self._clear_detail()
        if self._servers:
            self._list.setCurrentRow(0)
        else:
            self._show_empty_detail()

    def _clear_detail(self) -> None:
        while self._detail_layout.count():
            child = self._detail_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

    def _show_empty_detail(self) -> None:
        lab = QLabel(
            "Nenhum MCP server configurado.\n\n"
            "Adicione em ~/.claude.json:\n"
            "  mcpServers: { nome: { command: '…', args: ['…'] } }"
        )
        lab.setStyleSheet("color: #888;")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_layout.addWidget(lab)

    def _render_detail(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        s = items[0].data(Qt.ItemDataRole.UserRole)
        if not isinstance(s, McpServerEntry):
            return
        self._clear_detail()

        title = QLabel(f"<h2 style='margin:0;'>{s.name}</h2>")
        self._detail_layout.addWidget(title)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(QLabel(
            f"<span style='color:{_SCOPE_COLOR.get(s.scope,'#888')};'>"
            f"● {s.scope}</span>"
        ))
        chip_row.addWidget(QLabel(
            f"<span style='color:{_TRANSPORT_COLOR.get(s.transport,'#888')};'>"
            f"⇄ {s.transport}</span>"
        ))
        chip_row.addStretch()
        self._detail_layout.addLayout(chip_row)

        meta_box = QGroupBox("Configuração")
        meta_l = QFormLayout(meta_box)
        meta_l.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        if s.command:
            meta_l.addRow("<b>command</b>", QLabel(f"<code>{s.command}</code>"))
        if s.args:
            args_str = "<br>".join(f"<code>{mask_sensitive(a)}</code>" for a in s.args)
            args_lab = QLabel(args_str)
            args_lab.setWordWrap(True)
            args_lab.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            meta_l.addRow("<b>args</b>", args_lab)
        if s.url:
            url_lab = QLabel(f"<code>{mask_sensitive(s.url)}</code>")
            url_lab.setWordWrap(True)
            url_lab.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            meta_l.addRow("<b>url</b>", url_lab)
        if s.env_keys:
            env_str = ", ".join(f"<code>{k}</code>" for k in s.env_keys)
            env_lab = QLabel(f"{env_str}  <i style='color:#888;'>(valores ocultos)</i>")
            env_lab.setWordWrap(True)
            meta_l.addRow("<b>env</b>", env_lab)
        meta_l.addRow("<b>source</b>", QLabel(f"<code>{s.source_file}</code>"))
        self._detail_layout.addWidget(meta_box)

        preview_box = QGroupBox("Linha de comando aproximada")
        pl = QVBoxLayout(preview_box)
        preview = QTextBrowser()
        preview.setPlainText(mask_sensitive(s.cli_preview()))
        preview.setMaximumHeight(80)
        pl.addWidget(preview)
        self._detail_layout.addWidget(preview_box)

        self._detail_layout.addStretch()

    def _open_user_config(self) -> None:
        from pathlib import Path
        self._open_path(str(Path.home()))

    def _open_project_config(self) -> None:
        if not self.workspace or not self.workspace.folders:
            return
        self._open_path(self.workspace.folders[0])

    def _open_path(self, path: str) -> None:
        try:
            open_in_file_manager(path)
        except LaunchError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Falha ao abrir", str(e))
