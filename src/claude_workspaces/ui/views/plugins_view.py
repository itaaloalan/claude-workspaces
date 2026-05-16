"""Plugins instalados como view top-level.

Layout: toolbar (instalar de pasta · recarregar) · split list/detail.

Lista mostra plugins instalados; detalhe mostra manifest, permissões,
último diretório de logs. Toggle enable/disable persiste em
`<install>/.state/enabled.flag`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...errors import LaunchError
from ...launchers import LauncherError, find_app_repo_root, launch_claude_in_dir
from ...plugins import (
    InstalledPlugin,
    PluginRegistry,
    RegistryError,
    ValidationError,
)
from ...plugins.manifest_loader import load_manifest
from ...services.system_open import open_in_file_manager
from ...settings import Settings
from ..new_plugin_request_dialog import NewPluginRequestDialog

log = logging.getLogger(__name__)


_STATUS_COLOR = {True: "#5ac35a", False: "#888"}


class PluginsView(QWidget):
    """Lista + gerencia plugins instalados.

    Opcional `runtime_reloader`: callable que é chamado após install/uninstall/
    enable/disable pra que o PluginRuntime recarregue o plugin afetado.
    Se None, mudanças só vigoram no próximo restart."""

    # Emitido quando a lista de plugins muda (host pode recarregar tudo)
    plugins_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(parent)
        self.registry = PluginRegistry()
        self._plugins: list[InstalledPlugin] = []
        self._runtime_reloader = None  # injected by MainWindow
        self._settings = settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("<h2 style='margin:0;'>🧩 Plugins</h2>"))
        toolbar.addStretch()
        new_btn = QPushButton("✨ Solicitar novo plugin")
        new_btn.setToolTip(
            "Monta um pedido seguindo o PLUGIN_SPEC pra mandar pro Claude"
        )
        new_btn.clicked.connect(self._open_new_plugin_request)
        toolbar.addWidget(new_btn)

        # Botão "Exemplos" — só aparece se acharmos examples/plugins/ no repo
        self._examples_btn: QToolButton | None = None
        examples = self._discover_examples()
        if examples:
            ex_btn = QToolButton()
            ex_btn.setText("📦 Exemplos ▾")
            ex_btn.setToolTip(
                "Instala um dos bundles de exemplo que vêm com o app — "
                "um clique, sem precisar escolher pasta"
            )
            ex_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(ex_btn)
            for entry in examples:
                act = QAction(f"{entry['name']}   ·   {entry['description']}", menu)
                act.setToolTip(str(entry["path"]))
                act.triggered.connect(
                    lambda _checked=False, p=entry["path"]: self._install_example(p)
                )
                menu.addAction(act)
            ex_btn.setMenu(menu)
            ex_btn.setStyleSheet(
                "QToolButton { padding: 4px 10px; }"
            )
            toolbar.addWidget(ex_btn)
            self._examples_btn = ex_btn

        install_btn = QPushButton("📂 Instalar de pasta…")
        install_btn.setToolTip("Selecione a pasta do bundle (com plugin.yaml na raiz)")
        install_btn.clicked.connect(self._install_from_folder)
        toolbar.addWidget(install_btn)
        refresh_btn = QPushButton("↻ Recarregar")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        outer.addLayout(toolbar)

        # Explicação amigável (pra quem nunca mexeu com plugin)
        explain_card = QFrame()
        explain_card.setStyleSheet(
            "QFrame { background: #1d2733; border: 1px solid #2c3e54; "
            "border-radius: 8px; }"
        )
        ex_l = QVBoxLayout(explain_card)
        ex_l.setContentsMargins(14, 12, 14, 12)
        ex_l.setSpacing(6)

        ex_title_row = QHBoxLayout()
        ex_title_row.setSpacing(8)
        ex_title = QLabel(
            "<b style='color:#cfe2ff;'>💡 Primeira vez aqui? "
            "O que é um plugin?</b>"
        )
        ex_title_row.addWidget(ex_title)
        ex_title_row.addStretch()
        self._explain_toggle = QToolButton()
        self._explain_toggle.setText("ocultar")
        self._explain_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._explain_toggle.setStyleSheet(
            "QToolButton { color: #8fb4e0; background: transparent; "
            "border: none; padding: 2px 6px; }"
            "QToolButton:hover { color: #cfe2ff; }"
        )
        self._explain_toggle.clicked.connect(self._toggle_explain)
        ex_title_row.addWidget(self._explain_toggle)
        ex_l.addLayout(ex_title_row)

        self._explain_body = QLabel(
            "<div style='color:#d4dae3; line-height:150%;'>"
            "Pense num plugin como um <b>mini-app</b> que você encaixa aqui dentro "
            "pra ganhar uma habilidade nova — sem precisar programar nada.<br><br>"
            "Cada plugin pode, por exemplo:"
            "<ul style='margin-top:2px;'>"
            "<li><b>Adicionar um comando</b> que você dispara pela paleta "
            "(<code>Ctrl+P</code>) — tipo \"limpar cache\" ou \"abrir relatório\".</li>"
            "<li><b>Reagir a eventos</b> do app (um <i>hook</i>) — por exemplo, "
            "rodar algo toda vez que uma sessão começa.</li>"
            "<li><b>Mostrar um painel próprio</b> na interface, com botões e "
            "informações daquele plugin.</li>"
            "</ul>"
            "<b>Como usar na prática:</b><br>"
            "1. <b>Quer experimentar agora?</b> Clique em "
            "<b>📦 Exemplos ▾</b> ali em cima e escolha um — vai instalar "
            "na hora, sem precisar selecionar pasta.<br>"
            "2. Pra instalar um plugin externo, use <b>📂 Instalar de pasta…</b> "
            "e aponte pra pasta que tem o <code>plugin.yaml</code>.<br>"
            "3. Plugins instalados aparecem na lista abaixo. Use o switch "
            "<b>Habilitado</b> pra ligar/desligar quando quiser.<br>"
            "4. Cada plugin pede só as <b>permissões</b> que precisa "
            "(ler pastas, acessar a internet, etc.) — você vê tudo antes."
            "</div>"
        )
        self._explain_body.setWordWrap(True)
        self._explain_body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        ex_l.addWidget(self._explain_body)
        outer.addWidget(explain_card)

        hint = QLabel(
            "<span style='color:#8a8a8a;'>Detalhes técnicos:</span> "
            "plugins estendem o app via hooks/commands/panels. Instalados em "
            f"<code>{self.registry.root}</code>. Spec completa em "
            "<code>docs/PLUGIN_SPEC.md</code>."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b0b0b0;")
        outer.addWidget(hint)

        # Split list / detail
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)
        splitter.setStyleSheet(
            "QSplitter::handle { background: #2a2a2a; }"
            "QSplitter::handle:hover { background: #3d6ea8; }"
        )

        # Left: list
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(4)
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background: #181818; border: 1px solid #2c2c2c; "
            "border-radius: 6px; color: #e6e6e6; }"
            "QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #232323; }"
            "QListWidget::item:selected { background: #3d6ea8; color: #fff; }"
        )
        self._list.itemSelectionChanged.connect(self._render_detail)
        left_l.addWidget(self._list, stretch=1)
        self._counter = QLabel()
        self._counter.setStyleSheet("color: #888; font-size: 11px;")
        left_l.addWidget(self._counter)
        splitter.addWidget(left)

        # Right: detail container
        self._detail_scroll = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_scroll)
        self._detail_layout.setContentsMargins(8, 0, 0, 0)
        self._detail_layout.setSpacing(10)
        splitter.addWidget(self._detail_scroll)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 700])
        outer.addWidget(splitter, stretch=1)

        self.refresh()

    # ----- API pública ------------------------------------------------------

    def set_runtime_reloader(self, fn) -> None:
        """MainWindow injeta callable que aciona PluginRuntime quando algo muda."""
        self._runtime_reloader = fn

    def refresh(self) -> None:
        try:
            self._plugins = self.registry.list_installed()
        except Exception:
            log.exception("Falha listando plugins instalados")
            self._plugins = []

        self._list.clear()
        for inst in self._plugins:
            label = (
                f"{inst.manifest.name}  ·  v{inst.manifest.version}\n"
                f"{inst.id}"
            )
            li = QListWidgetItem(label)
            li.setData(Qt.ItemDataRole.UserRole, inst)
            chip = "✅ ativo" if inst.enabled else "⛔ desabilitado"
            li.setToolTip(
                f"{chip}\n{inst.manifest.description}\n{inst.install_dir}"
            )
            li.setForeground(
                QBrush(QColor(_STATUS_COLOR[inst.enabled]))
            )
            self._list.addItem(li)

        self._counter.setText(f"{len(self._plugins)} plugin(s) instalado(s)")
        self._clear_detail()
        if self._plugins:
            self._list.setCurrentRow(0)
        else:
            self._show_empty_detail()

    def _toggle_explain(self) -> None:
        visible = self._explain_body.isVisible()
        self._explain_body.setVisible(not visible)
        self._explain_toggle.setText("mostrar" if visible else "ocultar")

    # ----- detalhe ----------------------------------------------------------

    def _clear_detail(self) -> None:
        self._clear_layout(self._detail_layout)

    @staticmethod
    def _clear_layout(layout) -> None:
        # Sub-layouts (chip_row, action_row) parentam seus botões a
        # _detail_scroll — sem descer recursivamente, eles viram fantasmas.
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                PluginsView._clear_layout(sub)
                sub.deleteLater()

    def _show_empty_detail(self) -> None:
        lab = QLabel(
            "Nenhum plugin instalado.\n\n"
            "Clique em '📂 Instalar de pasta…' acima e selecione a pasta de "
            "um bundle (com plugin.yaml na raiz)."
        )
        lab.setStyleSheet("color: #888;")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_layout.addWidget(lab)

    def _render_detail(self) -> None:
        items = self._list.selectedItems()
        if not items:
            return
        inst = items[0].data(Qt.ItemDataRole.UserRole)
        if not isinstance(inst, InstalledPlugin):
            return
        self._clear_detail()

        m = inst.manifest
        title = QLabel(f"<h2 style='margin:0;'>{m.name}</h2>")
        self._detail_layout.addWidget(title)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        chip_row.addWidget(QLabel(
            f"<span style='color:{_STATUS_COLOR[inst.enabled]};'>"
            f"● {'ativo' if inst.enabled else 'desabilitado'}</span>"
        ))
        chip_row.addWidget(QLabel(
            f"<span style='color:#b0b0b0;'>v{m.version}</span>"
        ))
        chip_row.addWidget(QLabel(
            f"<span style='color:#888;'>por {m.author}</span>"
        ))
        chip_row.addStretch()

        toggle = QCheckBox("Habilitado")
        toggle.setChecked(inst.enabled)
        toggle.toggled.connect(lambda checked, p=inst: self._toggle_enabled(p, checked))
        chip_row.addWidget(toggle)
        self._detail_layout.addLayout(chip_row)

        desc = QLabel(m.description or "<i>(sem descrição)</i>")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #d0d0d0;")
        self._detail_layout.addWidget(desc)

        # Identidade + paths
        meta_box = QGroupBox("Identidade")
        meta_l = QFormLayout(meta_box)
        meta_l.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        meta_l.addRow("<b>id</b>", QLabel(f"<code>{m.id}</code>"))
        meta_l.addRow("<b>licença</b>", QLabel(f"<code>{m.license}</code>"))
        meta_l.addRow("<b>engine</b>", QLabel(f"<code>{m.engine.claude_workspaces}</code>"))
        if m.homepage:
            link = QLabel(f"<a href='{m.homepage}'>{m.homepage}</a>")
            link.setOpenExternalLinks(True)
            meta_l.addRow("<b>homepage</b>", link)
        meta_l.addRow("<b>install</b>", QLabel(f"<code>{inst.install_dir}</code>"))
        self._detail_layout.addWidget(meta_box)

        # Extensões
        ext_lines = []
        if m.commands:
            ext_lines.append(
                f"<b>commands</b> ({len(m.commands)}): "
                + ", ".join(f"<code>{c.id}</code>" for c in m.commands)
            )
        if m.hooks:
            ext_lines.append(
                f"<b>hooks</b> ({len(m.hooks)}): "
                + ", ".join(f"<code>{h.event}</code>" for h in m.hooks)
            )
        if m.panels:
            ext_lines.append(
                f"<b>panels</b> ({len(m.panels)}): "
                + ", ".join(f"<code>{p.id}@{p.slot.value}</code>" for p in m.panels)
            )
        if ext_lines:
            ext_box = QGroupBox("Extensões")
            ext_l = QVBoxLayout(ext_box)
            for line in ext_lines:
                lab = QLabel(line)
                lab.setWordWrap(True)
                ext_l.addWidget(lab)
            self._detail_layout.addWidget(ext_box)

        # Permissões
        p = m.permissions
        perm_lines = []
        if p.filesystem.read:
            perm_lines.append(
                "<b>fs.read</b>: " + ", ".join(
                    f"<code>{g}</code>" for g in p.filesystem.read
                )
            )
        if p.filesystem.write:
            perm_lines.append(
                "<b>fs.write</b>: " + ", ".join(
                    f"<code>{g}</code>" for g in p.filesystem.write
                )
            )
        if p.network.hosts:
            perm_lines.append(
                "<b>network</b>: " + ", ".join(
                    f"<code>{h}</code>" for h in p.network.hosts
                )
            )
        if p.notifications:
            perm_lines.append("<b>notifications</b>: sim")
        ws_str = (
            "todos"
            if p.workspaces == "all"
            else ", ".join(f"<code>{w}</code>" for w in p.workspaces)
        )
        perm_lines.append(f"<b>workspaces</b>: {ws_str}")
        perm_box = QGroupBox("Permissões")
        perm_l = QVBoxLayout(perm_box)
        if not perm_lines:
            perm_l.addWidget(QLabel("<i>(nenhuma declarada)</i>"))
        else:
            for line in perm_lines:
                lab = QLabel(line)
                lab.setWordWrap(True)
                perm_l.addWidget(lab)
        self._detail_layout.addWidget(perm_box)

        # Config exposta
        if m.config:
            cfg_box = QGroupBox("Configurações expostas")
            cfg_l = QFormLayout(cfg_box)
            for f in m.config:
                lab_text = f"<b>{f.label}</b><br><code>{f.key}</code>"
                value_text = (
                    f"default: <code>{f.default}</code>  "
                    f"<span style='color:#888;'>· tipo: {f.type.value}</span>"
                )
                cfg_l.addRow(QLabel(lab_text), QLabel(value_text))
            self._detail_layout.addWidget(cfg_box)

        # Ações finais
        action_row = QHBoxLayout()
        action_row.addStretch()
        open_dir_btn = QPushButton("📂 Abrir pasta")
        open_dir_btn.setToolTip("Abre o diretório de instalação")
        open_dir_btn.clicked.connect(
            lambda _, d=str(inst.install_dir): self._open_path(d)
        )
        action_row.addWidget(open_dir_btn)

        logs_dir = inst.install_dir / ".logs"
        open_logs_btn = QPushButton("📜 Ver logs")
        open_logs_btn.setEnabled(logs_dir.exists())
        open_logs_btn.setToolTip(
            "Abre o diretório de logs do plugin"
            if logs_dir.exists()
            else "Plugin ainda não gerou logs"
        )
        open_logs_btn.clicked.connect(lambda _, d=str(logs_dir): self._open_path(d))
        action_row.addWidget(open_logs_btn)

        uninstall_btn = QPushButton("🗑 Desinstalar")
        uninstall_btn.setStyleSheet(
            "QPushButton { color: #d57272; }"
            "QPushButton:hover { background: #3a1f1f; }"
        )
        uninstall_btn.clicked.connect(lambda _, p=inst: self._uninstall(p))
        action_row.addWidget(uninstall_btn)
        self._detail_layout.addLayout(action_row)

        self._detail_layout.addStretch()

    # ----- ações ------------------------------------------------------------

    def _open_new_plugin_request(self) -> None:
        dialog = NewPluginRequestDialog(parent=self)
        repo = find_app_repo_root()
        can_launch = self._settings is not None and repo is not None
        dialog.enable_launch(can_launch)
        if not dialog.exec():
            return
        # Accept = "Abrir Claude com este pedido"
        briefing = dialog.briefing()
        if not briefing:
            return
        QGuiApplication.clipboard().setText(briefing)
        if not can_launch:
            QMessageBox.information(
                self,
                "Pedido copiado",
                "O pedido está no clipboard. Cole numa sessão do Claude.",
            )
            return
        try:
            launch_claude_in_dir(repo, self._settings)
        except LauncherError as e:
            QMessageBox.warning(
                self,
                "Falha ao abrir Claude",
                f"{e}<br><br>O pedido continua no clipboard.",
            )
            return
        QMessageBox.information(
            self,
            "Claude aberto",
            "Pedido no clipboard. Quando o Claude estiver pronto, cole "
            "(Ctrl+Shift+V) pra enviar.",
        )

    def _install_from_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Selecione a pasta do bundle (com plugin.yaml na raiz)"
        )
        if not folder:
            return
        path = Path(folder)
        if not (path / "plugin.yaml").exists():
            QMessageBox.warning(
                self,
                "Bundle inválido",
                f"Não encontrei <code>plugin.yaml</code> em {path}.",
            )
            return
        try:
            inst = self.registry.install(path, overwrite=False)
        except ValidationError as e:
            QMessageBox.warning(
                self,
                "Validação falhou",
                "<b>O bundle não passou na validação:</b><br><br>"
                + "<br>".join(f"• {x}" for x in e.errors[:20]),
            )
            return
        except RegistryError as e:
            # já existe — pergunta se quer reinstalar
            reply = QMessageBox.question(
                self,
                "Plugin já instalado",
                f"{e}<br><br>Reinstalar (substitui o existente)?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                inst = self.registry.install(path, overwrite=True)
            except (ValidationError, RegistryError) as e2:
                QMessageBox.warning(self, "Falha no reinstall", str(e2))
                return

        self._after_change(inst.id, "load")
        QMessageBox.information(
            self,
            "Plugin instalado",
            f"<b>{inst.manifest.name}</b> v{inst.manifest.version} pronto.",
        )

    def _uninstall(self, inst: InstalledPlugin) -> None:
        reply = QMessageBox.question(
            self,
            "Desinstalar plugin",
            f"Remover <b>{inst.manifest.name}</b> ({inst.id}) permanentemente?<br>"
            f"Storage e logs vão junto.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.registry.uninstall(inst.id)
        except RegistryError as e:
            QMessageBox.warning(self, "Falha ao desinstalar", str(e))
            return
        self._after_change(inst.id, "unload")

    def _toggle_enabled(self, inst: InstalledPlugin, enabled: bool) -> None:
        try:
            self.registry.set_enabled(inst.id, enabled)
        except RegistryError as e:
            QMessageBox.warning(self, "Falha", str(e))
            return
        self._after_change(inst.id, "load" if enabled else "unload")

    def _after_change(self, plugin_id: str, action: str) -> None:
        """Aciona o runtime e recarrega a lista.

        action: 'load' (depois de install/enable) ou 'unload' (uninstall/disable)."""
        if self._runtime_reloader is not None:
            try:
                self._runtime_reloader(plugin_id, action)
            except Exception:
                log.exception("Falha acionando runtime reloader")
        self.refresh()
        self.plugins_changed.emit()

    def _open_path(self, path: str) -> None:
        try:
            open_in_file_manager(path)
        except LaunchError as e:
            QMessageBox.warning(self, "Falha ao abrir", str(e))

    # ----- exemplos prontos -------------------------------------------------

    def _discover_examples(self) -> list[dict]:
        """Procura bundles em examples/plugins/ do repo (quando rodando do source).

        Retorna lista de dicts com `name`, `description`, `path`. Ordem
        alfabética por nome. Falhas de parsing de algum exemplo são engolidas
        (são bundles do projeto, não input do usuário — se quebrarem, o
        analyzer principal pega depois)."""
        repo = find_app_repo_root()
        if repo is None:
            return []
        examples_dir = repo / "examples" / "plugins"
        if not examples_dir.is_dir():
            return []
        out: list[dict] = []
        for child in sorted(examples_dir.iterdir()):
            if not (child / "plugin.yaml").is_file():
                continue
            try:
                m = load_manifest(child)
                name = m.name
                desc = m.description
            except Exception:  # noqa: BLE001
                name = child.name
                desc = ""
            out.append({"name": name, "description": desc, "path": child})
        return out

    def _install_example(self, path: Path) -> None:
        """Instala um exemplo direto, perguntando antes de sobrescrever."""
        try:
            inst = self.registry.install(path, overwrite=False)
        except ValidationError as e:
            QMessageBox.warning(
                self,
                "Validação falhou",
                "<b>O exemplo não passou na validação:</b><br><br>"
                + "<br>".join(f"• {x}" for x in e.errors[:20]),
            )
            return
        except RegistryError as e:
            reply = QMessageBox.question(
                self,
                "Exemplo já instalado",
                f"{e}<br><br>Reinstalar (substitui o existente)?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                inst = self.registry.install(path, overwrite=True)
            except (ValidationError, RegistryError) as e2:
                QMessageBox.warning(self, "Falha no reinstall", str(e2))
                return

        self._after_change(inst.id, "load")
        QMessageBox.information(
            self,
            "Exemplo instalado",
            f"<b>{inst.manifest.name}</b> v{inst.manifest.version} pronto.",
        )
