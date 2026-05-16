"""Dialog pra solicitar a criação de um novo plugin via Claude.

O usuário descreve o que quer, e o dialog monta um briefing estruturado
seguindo o `docs/PLUGIN_SPEC.md`. O briefing pode ser copiado pro clipboard
ou usado pra abrir uma nova sessão do Claude no repo do app.
"""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)


def _slugify_id(name: str) -> str:
    """Tenta gerar um id reverse-DNS razoável a partir do nome."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not base:
        return ""
    return f"local.{base}"


class NewPluginRequestDialog(QDialog):
    """Coleta a ideia do plugin e monta um briefing pronto pro Claude."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Solicitar criação de novo plugin")
        self.resize(760, 640)

        outer = QVBoxLayout(self)
        outer.setSpacing(10)

        intro = QLabel(
            "Descreva o plugin que você quer. A gente monta um pedido "
            "estruturado seguindo o <code>docs/PLUGIN_SPEC.md</code> e "
            "você manda pro Claude — ele scaffolda o bundle pra você."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        outer.addWidget(intro)

        # --- Formulário ----------------------------------------------------
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name = QLineEdit()
        self._name.setPlaceholderText("Ex.: Sessão Watcher")
        self._name.textChanged.connect(self._on_name_changed)
        form.addRow("<b>Nome</b>", self._name)

        self._id = QLineEdit()
        self._id.setPlaceholderText("Ex.: local.sessao-watcher (reverse-DNS)")
        self._id.textChanged.connect(self._update_preview)
        form.addRow("<b>ID sugerido</b>", self._id)

        self._goal = QPlainTextEdit()
        self._goal.setPlaceholderText(
            "Em uma frase, o que o plugin deve fazer pra você.\n"
            "Ex.: avisar quando uma sessão fica mais de 5min sem responder."
        )
        self._goal.setFixedHeight(70)
        self._goal.textChanged.connect(self._update_preview)
        form.addRow("<b>Objetivo</b>", self._goal)

        # Tipos de extensão
        ext_row = QHBoxLayout()
        ext_row.setSpacing(12)
        self._chk_commands = QCheckBox("Commands (paleta Ctrl+P)")
        self._chk_hooks = QCheckBox("Hooks (reagir a eventos)")
        self._chk_panels = QCheckBox("Panels (UI própria)")
        for chk in (self._chk_commands, self._chk_hooks, self._chk_panels):
            chk.toggled.connect(self._update_preview)
            ext_row.addWidget(chk)
        ext_row.addStretch()
        ext_holder = QWidget()
        ext_holder.setLayout(ext_row)
        form.addRow("<b>Extensões</b>", ext_holder)

        self._perms = QPlainTextEdit()
        self._perms.setPlaceholderText(
            "Opcional. Globs de leitura/escrita, domínios de rede, "
            "se precisa notificar etc.\n"
            "Ex.: ler ~/.claude/projects, notificar."
        )
        self._perms.setFixedHeight(60)
        self._perms.textChanged.connect(self._update_preview)
        form.addRow("<b>Permissões</b>", self._perms)

        self._notes = QPlainTextEdit()
        self._notes.setPlaceholderText(
            "Opcional. Restrições, preferências de design, exemplos de uso, "
            "config exposta ao usuário etc."
        )
        self._notes.setFixedHeight(60)
        self._notes.textChanged.connect(self._update_preview)
        form.addRow("<b>Notas</b>", self._notes)

        outer.addLayout(form)

        # --- Preview do briefing -------------------------------------------
        preview_label = QLabel(
            "<b>Pedido gerado</b> "
            "<span style='color:#888;'>(edite à vontade antes de enviar)</span>"
        )
        outer.addWidget(preview_label)

        self._preview = QPlainTextEdit()
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._preview.setFont(mono)
        self._preview.setStyleSheet(
            "QPlainTextEdit {"
            "  background: #181818; border: 1px solid #2c2c2c;"
            "  border-radius: 6px; color: #e6e6e6; padding: 8px;"
            "}"
            "QPlainTextEdit:focus { border-color: #3d6ea8; }"
        )
        outer.addWidget(self._preview, stretch=1)

        # --- Botões --------------------------------------------------------
        buttons = QDialogButtonBox()
        self._copy_btn = QPushButton("📋 Copiar pedido")
        self._copy_btn.clicked.connect(self._copy_to_clipboard)
        buttons.addButton(self._copy_btn, QDialogButtonBox.ButtonRole.ActionRole)

        self._launch_btn = QPushButton("🚀 Abrir Claude com este pedido")
        self._launch_btn.setToolTip(
            "Abre uma nova sessão do Claude no repo do app, "
            "com o pedido já no clipboard pra colar."
        )
        self._launch_btn.clicked.connect(self.accept)
        buttons.addButton(self._launch_btn, QDialogButtonBox.ButtonRole.AcceptRole)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.reject)
        buttons.addButton(close_btn, QDialogButtonBox.ButtonRole.RejectRole)

        outer.addWidget(buttons)

        # Estado inicial — sem launcher injetado, esconde botão de lançar
        self._launch_btn.setVisible(False)

        self._update_preview()

    # ----- API pública ------------------------------------------------------

    def enable_launch(self, enabled: bool) -> None:
        """Habilita o botão de abrir Claude. MainWindow chama isso quando
        sabe que dá pra lançar (settings + repo root disponíveis)."""
        self._launch_btn.setVisible(enabled)

    def briefing(self) -> str:
        return self._preview.toPlainText().strip()

    # ----- internos ---------------------------------------------------------

    def _on_name_changed(self, txt: str) -> None:
        # autopreenche o id sugerido só enquanto o usuário não tocou nele
        if not self._id.isModified():
            self._id.setText(_slugify_id(txt))
            self._id.setModified(False)
        self._update_preview()

    def _selected_extensions(self) -> list[str]:
        picks = []
        if self._chk_commands.isChecked():
            picks.append("commands")
        if self._chk_hooks.isChecked():
            picks.append("hooks")
        if self._chk_panels.isChecked():
            picks.append("panels")
        return picks

    def _update_preview(self) -> None:
        name = self._name.text().strip() or "<NOME-DO-PLUGIN>"
        plug_id = self._id.text().strip() or "local.<id-do-plugin>"
        goal = self._goal.toPlainText().strip() or "<descreva em uma frase>"
        exts = self._selected_extensions() or ["<defina o tipo de extensão>"]
        perms = self._perms.toPlainText().strip() or "(nenhuma específica — só o mínimo)"
        notes = self._notes.toPlainText().strip() or "(sem notas adicionais)"

        briefing = (
            "Quero criar um plugin novo pro Claude Workspaces. "
            "Siga estritamente `docs/PLUGIN_SPEC.md` (v2.0) e use "
            "`examples/plugins/sessao-watcher/` como referência de layout.\n"
            "\n"
            "## Identidade\n"
            f"- **Nome**: {name}\n"
            f"- **ID** (reverse-DNS): `{plug_id}`\n"
            "- **Versão inicial**: 0.1.0\n"
            "- **Autor**: Italo Alan\n"
            "- **Licença**: MIT\n"
            "\n"
            "## Objetivo\n"
            f"{goal}\n"
            "\n"
            "## Extensões a implementar\n"
            + "\n".join(f"- {e}" for e in exts)
            + "\n"
            "\n"
            "## Permissões desejadas\n"
            f"{perms}\n"
            "\n"
            "## Notas extras\n"
            f"{notes}\n"
            "\n"
            "## O que eu espero como entrega\n"
            "1. Scaffold completo do bundle em "
            "`examples/plugins/<id-sem-prefixo>/` com `plugin.yaml`, "
            "`README.md` (PT-BR, >100 chars), `src/__init__.py` e os "
            "handlers `.py` correspondentes às extensões acima.\n"
            "2. Manifesto declarando **só** as permissões usadas — "
            "lembra que a validação faz análise estática AST e rejeita "
            "permissão declarada que não é usada (e vice-versa).\n"
            "3. Handlers `async def handler(ctx, payload?)` para "
            "commands/hooks; handler síncrono retornando `QWidget` "
            "para panels.\n"
            "4. Imports só relativos ou do allowlist "
            "(`claude_workspaces.plugin_api` + stdlib seguro).\n"
            "5. Sem `setup.py`, `requirements.txt`, `.pyc`, "
            "`__pycache__/`, `.venv/`, `node_modules/`.\n"
            "6. README explicando o que o plugin faz, como instalar pela "
            "página de Plugins do app e como configurar.\n"
            "\n"
            "Quando terminar, me diga o caminho exato da pasta pra eu "
            "instalar via **📂 Instalar de pasta…** na página de Plugins."
        )
        self._preview.setPlainText(briefing)

    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setText(self.briefing())
        self._copy_btn.setText("✓ Copiado")
        # restaura o texto após um beat (sem timer extra — só repinta)
        self._copy_btn.setEnabled(False)

        def _restore() -> None:
            self._copy_btn.setText("📋 Copiar pedido")
            self._copy_btn.setEnabled(True)

        from PySide6.QtCore import QTimer

        QTimer.singleShot(1200, _restore)
