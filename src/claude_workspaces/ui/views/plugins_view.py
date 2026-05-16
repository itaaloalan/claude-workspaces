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
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
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
from ...plugins.config_store import PluginConfigStore
from ...plugins.manifest import ConfigFieldType
from ...plugins.manifest_loader import load_manifest
from ...services.system_open import open_in_file_manager
from ...settings import Settings
from ..new_plugin_request_dialog import NewPluginRequestDialog

log = logging.getLogger(__name__)


_STATUS_COLOR = {True: "#5ac35a", False: "#888"}

# Eventos técnicos → descrição amigável (qual situação real dispara isso).
# Fonte de verdade: docs/PLUGIN_SPEC.md §7. Se um evento novo for
# adicionado lá e não aqui, cai num fallback genérico.
_EVENT_HUMAN: dict[str, str] = {
    "session.created": "uma nova sessão é criada",
    "session.status-changed": "uma sessão muda de status (rodando, parada, etc.)",
    "session.message-sent": "você envia uma mensagem numa sessão",
    "session.completed": "uma sessão termina",
    "workspace.opened": "você abre um workspace",
    "workspace.closed": "um workspace é fechado",
    "commit.created": "um novo commit aparece num workspace",
    "plugin.config-changed": "você muda alguma configuração desse próprio plugin",
}

_PANEL_SLOT_HUMAN: dict[str, str] = {
    "sidebar-top": "na barra lateral (topo)",
    "sidebar-bottom": "na barra lateral (rodapé)",
    "workspace-tab": "como aba dentro do workspace",
}


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

        # Right: detail container (scrollable — sem isso o conteúdo
        # comprime e fica ilegível quando a janela é curta)
        self._detail_scroll = QScrollArea()
        self._detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._detail_scroll.setWidgetResizable(True)
        self._detail_inner = QWidget()
        self._detail_layout = QVBoxLayout(self._detail_inner)
        self._detail_layout.setContentsMargins(8, 0, 8, 8)
        self._detail_layout.setSpacing(10)
        self._detail_scroll.setWidget(self._detail_inner)
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
        # Sub-layouts (chip_row, action_row) parentam seus botões ao
        # _detail_inner — sem descer recursivamente, eles viram fantasmas.
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

        # "Como funciona" — explica em PT-BR claro se o plugin é automático,
        # manual, visual ou combinação. Resolve a dúvida principal do usuário
        # ("isso roda sozinho ou eu preciso fazer algo?") antes dele cair nas
        # listas técnicas abaixo.
        how_card = self._build_how_it_works_card(m)
        if how_card is not None:
            self._detail_layout.addWidget(how_card)

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

        # Extensões — uma linha por extensão, com ícone que diferencia o que
        # roda sozinho do que você precisa ativar manualmente. Identificador
        # técnico vai num <span> apagado pra quem precisa, sem poluir.
        if m.commands or m.hooks or m.panels:
            ext_box = QGroupBox("O que esse plugin entrega")
            ext_l = QVBoxLayout(ext_box)
            ext_l.setSpacing(6)
            for c in m.commands:
                ext_l.addWidget(self._ext_line(
                    icon="▶️",
                    headline=f"Comando manual: <b>{c.title}</b>",
                    sub="Você dispara abrindo a paleta (<b>Ctrl+P</b>) e procurando "
                        "pelo nome. Não roda sozinho.",
                    tech=f"id: <code>{c.id}</code>",
                ))
            for h in m.hooks:
                event_label = _EVENT_HUMAN.get(
                    h.event, f"o evento <code>{h.event}</code>"
                )
                ext_l.addWidget(self._ext_line(
                    icon="🔁",
                    headline=f"Reage sozinho quando {event_label}",
                    sub="Funciona em segundo plano enquanto o plugin estiver "
                        "habilitado — você não precisa fazer nada.",
                    tech=f"evento: <code>{h.event}</code>",
                ))
            for p in m.panels:
                slot_label = _PANEL_SLOT_HUMAN.get(
                    p.slot.value, f"no slot <code>{p.slot.value}</code>"
                )
                ext_l.addWidget(self._ext_line(
                    icon="🪟",
                    headline=f"Painel: <b>{p.title}</b>",
                    sub=f"Aparece {slot_label} sempre que o plugin estiver "
                        "habilitado.",
                    tech=f"id: <code>{p.id}</code>",
                ))
            self._detail_layout.addWidget(ext_box)

        # Permissões — frase verbal ("Pode X") em vez de jargão técnico.
        # O plugin SÓ consegue fazer o que tá listado aqui; o resto é
        # bloqueado pelo runtime.
        p = m.permissions
        perm_box = QGroupBox("O que o plugin pode fazer no seu computador")
        perm_l = QVBoxLayout(perm_box)
        perm_l.setSpacing(6)
        perm_lines: list[tuple[str, str]] = []
        if p.filesystem.read:
            paths = ", ".join(f"<code>{g}</code>" for g in p.filesystem.read)
            perm_lines.append(("📂", f"<b>Ler arquivos</b> em: {paths}"))
        if p.filesystem.write:
            paths = ", ".join(f"<code>{g}</code>" for g in p.filesystem.write)
            perm_lines.append(("✏️", f"<b>Escrever arquivos</b> em: {paths}"))
        if p.network.hosts:
            hosts = ", ".join(f"<code>{h}</code>" for h in p.network.hosts)
            perm_lines.append(("🌐", f"<b>Acessar a internet</b>, só em: {hosts}"))
        if p.notifications:
            perm_lines.append(("🔔", "<b>Mostrar notificações</b> e avisos pra você"))
        if p.workspaces == "all":
            perm_lines.append(("🗂", "<b>Ver e agir em qualquer workspace</b> que você tiver"))
        elif p.workspaces:
            ws = ", ".join(f"<code>{w}</code>" for w in p.workspaces)
            perm_lines.append(("🗂", f"<b>Ver e agir só nestes workspaces</b>: {ws}"))
        if not perm_lines:
            perm_l.addWidget(QLabel(
                "<i style='color:#888;'>Plugin não pediu nenhuma permissão — "
                "fica isolado, sem tocar em arquivos nem internet.</i>"
            ))
        else:
            for icon, text in perm_lines:
                row = QHBoxLayout()
                row.setSpacing(8)
                icon_lab = QLabel(icon)
                icon_lab.setStyleSheet("font-size: 14px;")
                icon_lab.setFixedWidth(20)
                icon_lab.setAlignment(Qt.AlignmentFlag.AlignTop)
                row.addWidget(icon_lab)
                text_lab = QLabel(text)
                text_lab.setWordWrap(True)
                text_lab.setStyleSheet("color: #d0d0d0;")
                row.addWidget(text_lab, stretch=1)
                perm_l.addLayout(row)
        self._detail_layout.addWidget(perm_box)

        # Config editável — auto-save no commit (focus-out pra texto/número,
        # toggle pra bool, change pra enum). Cada save persiste no store e
        # aciona reload do plugin no runtime; o listener ctx.config.on_change
        # registrado pelo plugin recebe o valor novo no próximo load.
        if m.config:
            defaults = {f.key: f.default for f in m.config}
            store = PluginConfigStore(inst.install_dir, defaults)
            cfg_box = QGroupBox("Configurações")
            cfg_outer = QVBoxLayout(cfg_box)
            cfg_outer.setSpacing(8)
            hint = QLabel(
                "<span style='color:#9aa4b1;'>"
                "Mude qualquer valor abaixo e ele salva sozinho. O plugin "
                "recarrega na hora pra pegar o valor novo."
                "</span>"
            )
            hint.setWordWrap(True)
            cfg_outer.addWidget(hint)
            cfg_form = QFormLayout()
            cfg_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            cfg_form.setSpacing(8)
            for f in m.config:
                label_w = self._cfg_label(f)
                editor, status = self._cfg_editor(f, store, inst)
                # Cada linha empacota editor + status num container só
                # pro QFormLayout alinhar bonitinho.
                holder = QWidget()
                hl = QVBoxLayout(holder)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(2)
                hl.addWidget(editor)
                hl.addWidget(status)
                cfg_form.addRow(label_w, holder)
            cfg_outer.addLayout(cfg_form)
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

    # ----- helpers de explicação --------------------------------------------

    def _build_how_it_works_card(self, manifest) -> QFrame | None:
        """Card amarelo/verde que responde 'esse plugin roda sozinho?'.

        Combina as extensões pra montar uma frase que diga o que o usuário
        precisa fazer (ou não fazer) pra ver valor. Retorna None se o
        manifesto não declarou nenhuma extensão (não deveria acontecer pós-
        validação, mas defensivo)."""
        has_hooks = bool(manifest.hooks)
        has_commands = bool(manifest.commands)
        has_panels = bool(manifest.panels)
        if not (has_hooks or has_commands or has_panels):
            return None

        parts: list[str] = []
        if has_hooks:
            parts.append(
                "<b>roda em segundo plano</b> e reage sozinho a coisas que "
                "acontecem no app (você não precisa fazer nada)"
            )
        if has_commands:
            parts.append(
                "oferece <b>comandos manuais</b> que você dispara pela "
                "paleta com <b>Ctrl+P</b>"
            )
        if has_panels:
            parts.append(
                "mostra um <b>painel próprio</b> na interface enquanto "
                "estiver habilitado"
            )
        if len(parts) == 1:
            body = "Esse plugin " + parts[0] + "."
        else:
            body = "Esse plugin " + "; ".join(parts[:-1]) + "; e " + parts[-1] + "."

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #1d2733; border: 1px solid #2c3e54; "
            "border-radius: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)
        title = QLabel("<b style='color:#cfe2ff;'>💡 Como funciona</b>")
        layout.addWidget(title)
        text = QLabel(f"<div style='color:#d4dae3; line-height:150%;'>{body}</div>")
        text.setWordWrap(True)
        layout.addWidget(text)
        # Lembra do enable/disable, que é a única ação realmente necessária
        # pro hook/panel começar a agir.
        if has_hooks or has_panels:
            footer = QLabel(
                "<span style='color:#8fb4e0;'>Tudo isso só acontece com o "
                "switch <b>Habilitado</b> ligado.</span>"
            )
            footer.setWordWrap(True)
            layout.addWidget(footer)
        return card

    # ----- helpers de config editável ---------------------------------------

    def _cfg_label(self, field) -> QWidget:
        """Label da linha do form com label + key técnica embaixo."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QLabel(f"<b>{field.label}</b>")
        head.setWordWrap(True)
        v.addWidget(head)
        key = QLabel(f"<code style='color:#666; font-size:11px;'>{field.key}</code>")
        v.addWidget(key)
        return w

    def _cfg_editor(
        self, field, store: PluginConfigStore, inst: InstalledPlugin
    ) -> tuple[QWidget, QLabel]:
        """Constrói widget pro tipo do field e plugando o auto-save."""
        current = store.get(field.key)
        if current is None:
            current = field.default

        status = QLabel("")
        status.setStyleSheet("color: #6b7785; font-size: 11px;")

        def mark_saved() -> None:
            status.setText(
                "<span style='color:#5ac35a;'>✓ salvo</span>"
                if store.is_overridden(field.key)
                else "<span style='color:#888;'>· no padrão</span>"
            )

        def commit(value) -> None:
            # Se ficou idêntico ao default, remove o override em vez de
            # gravar o mesmo valor (evita poluir o JSON e fica óbvio
            # quando o usuário "tá no padrão").
            if value == field.default:
                store.reset(field.key)
            else:
                try:
                    store.set(field.key, value)
                except Exception:
                    log.exception("Falha salvando config %s.%s", inst.id, field.key)
                    status.setText("<span style='color:#d57272;'>erro ao salvar</span>")
                    return
            mark_saved()
            # Reload só se o plugin tá habilitado — recarregar disabled
            # não tem efeito útil e ainda assusta o usuário.
            if inst.enabled and self._runtime_reloader is not None:
                try:
                    self._runtime_reloader(inst.id, "load")
                except Exception:
                    log.exception("Falha recarregando plugin pós-config %s", inst.id)

        editor: QWidget
        ft = field.type
        if ft == ConfigFieldType.BOOLEAN:
            cb = QCheckBox()
            cb.setChecked(bool(current))
            cb.toggled.connect(commit)
            editor = cb
        elif ft == ConfigFieldType.INTEGER:
            sp = QSpinBox()
            # Spin precisa de bounds explícitos; manifesto pode dar min/max,
            # senão usamos uma janela ampla mas não absurda.
            sp.setMinimum(field.min if field.min is not None else -1_000_000)
            sp.setMaximum(field.max if field.max is not None else 1_000_000)
            try:
                sp.setValue(int(current))
            except (TypeError, ValueError):
                sp.setValue(int(field.default))
            sp.editingFinished.connect(lambda s=sp: commit(s.value()))
            editor = sp
        elif ft == ConfigFieldType.ENUM:
            cb_e = QComboBox()
            for opt in field.options:
                cb_e.addItem(opt)
            if current in field.options:
                cb_e.setCurrentText(str(current))
            cb_e.currentTextChanged.connect(commit)
            editor = cb_e
        else:  # STRING
            if field.multiline:
                te = QPlainTextEdit()
                te.setPlainText("" if current is None else str(current))
                te.setFixedHeight(80)
                # editingFinished não existe em QPlainTextEdit — usamos
                # focusOut via eventFilter? Pra manter simples, salvamos
                # no textChanged com um pequeno debounce via QTimer.
                from PySide6.QtCore import QTimer
                timer = QTimer(te)
                timer.setSingleShot(True)
                timer.setInterval(600)
                timer.timeout.connect(lambda t=te: commit(t.toPlainText()))
                te.textChanged.connect(timer.start)
                editor = te
            else:
                le = QLineEdit()
                le.setText("" if current is None else str(current))
                le.editingFinished.connect(lambda w=le: commit(w.text()))
                editor = le

        # Reset-pro-default só faz sentido se o valor atual difere do default.
        # Embrulhamos editor + botão num linha pra esquerda/direita.
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(editor, stretch=1)
        reset_btn = QToolButton()
        reset_btn.setText("↺")
        reset_btn.setToolTip("Voltar pro valor padrão do plugin")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(
            "QToolButton { color:#8fb4e0; background:transparent; "
            "border:none; padding:2px 6px; font-size:14px; }"
            "QToolButton:hover { color:#cfe2ff; }"
            "QToolButton:disabled { color:#444; }"
        )
        reset_btn.setEnabled(store.is_overridden(field.key))

        def do_reset() -> None:
            # Reaplica default no widget; commit() ainda roda e tira o override.
            d = field.default
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(d))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(d))
            elif isinstance(editor, QComboBox):
                editor.setCurrentText(str(d))
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlainText("" if d is None else str(d))
            elif isinstance(editor, QLineEdit):
                editor.setText("" if d is None else str(d))
            commit(d)
            reset_btn.setEnabled(False)

        reset_btn.clicked.connect(do_reset)

        # Mantém o estado do reset sincronizado com saves subsequentes.
        original_commit = commit

        def commit_then_refresh(value) -> None:
            original_commit(value)
            reset_btn.setEnabled(store.is_overridden(field.key))

        # Re-conecta os signals pro wrapper (substituindo o anterior).
        try:
            if isinstance(editor, QCheckBox):
                editor.toggled.disconnect()
                editor.toggled.connect(commit_then_refresh)
            elif isinstance(editor, QSpinBox):
                editor.editingFinished.disconnect()
                editor.editingFinished.connect(lambda s=editor: commit_then_refresh(s.value()))
            elif isinstance(editor, QComboBox):
                editor.currentTextChanged.disconnect()
                editor.currentTextChanged.connect(commit_then_refresh)
            elif isinstance(editor, QPlainTextEdit):
                # Mantém o timer; só troca o slot
                pass
            elif isinstance(editor, QLineEdit):
                editor.editingFinished.disconnect()
                editor.editingFinished.connect(
                    lambda w=editor: commit_then_refresh(w.text())
                )
        except (RuntimeError, TypeError):
            # disconnect() pode falhar em casos raros; safe no-op.
            pass

        rl.addWidget(reset_btn)
        mark_saved()
        return row, status

    def _ext_line(self, *, icon: str, headline: str, sub: str, tech: str) -> QFrame:
        """Renderiza uma linha de extensão: ícone grande + headline + sub + tech."""
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: transparent; border: none; }"
        )
        row = QHBoxLayout(frame)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        icon_lab = QLabel(icon)
        icon_lab.setStyleSheet("font-size: 18px;")
        icon_lab.setFixedWidth(24)
        icon_lab.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(icon_lab)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        head = QLabel(f"<div style='color:#e6e6e6;'>{headline}</div>")
        head.setWordWrap(True)
        text_col.addWidget(head)
        sub_lab = QLabel(f"<div style='color:#9aa4b1;'>{sub}</div>")
        sub_lab.setWordWrap(True)
        text_col.addWidget(sub_lab)
        tech_lab = QLabel(f"<span style='color:#666; font-size:11px;'>{tech}</span>")
        tech_lab.setWordWrap(True)
        text_col.addWidget(tech_lab)
        row.addLayout(text_col, stretch=1)
        return frame

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
