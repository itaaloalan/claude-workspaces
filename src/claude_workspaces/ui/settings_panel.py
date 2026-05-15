import shlex

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..settings import Settings, settings_file


class SettingsPanel(QWidget):
    settings_saved = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        title = QLabel("<h2>Configurações</h2>")
        outer.addWidget(title)

        intro = QLabel(
            "Customize os comandos usados pelos botões dos workspaces. "
            "O Claude e o terminal são lançados através do seu shell interativo "
            "($SHELL -ic), então aliases como <code>ia</code> resolvem normalmente."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aaa;")
        outer.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        self._claude_cmd = QLineEdit()
        self._claude_cmd.setPlaceholderText("claude")
        form.addRow("Comando do Claude:", self._claude_cmd)

        self._claude_args = QLineEdit()
        self._claude_args.setPlaceholderText("(opcional) ex: --dangerously-skip-permissions")
        form.addRow("Args extras do Claude:", self._claude_args)

        self._terminal_cmd = QLineEdit()
        self._terminal_cmd.setPlaceholderText("konsole")
        form.addRow("Terminal:", self._terminal_cmd)

        self._vscode_cmd = QLineEdit()
        self._vscode_cmd.setPlaceholderText("code")
        form.addRow("VS Code:", self._vscode_cmd)

        self._intellij_cmd = QLineEdit()
        self._intellij_cmd.setPlaceholderText("idea")
        form.addRow("IntelliJ IDEA:", self._intellij_cmd)

        self._webstorm_cmd = QLineEdit()
        self._webstorm_cmd.setPlaceholderText("webstorm")
        form.addRow("WebStorm:", self._webstorm_cmd)

        self._pycharm_cmd = QLineEdit()
        self._pycharm_cmd.setPlaceholderText("pycharm")
        form.addRow("PyCharm:", self._pycharm_cmd)

        self._rider_cmd = QLineEdit()
        self._rider_cmd.setPlaceholderText("rider")
        form.addRow("Rider:", self._rider_cmd)

        outer.addLayout(form)

        actions = QHBoxLayout()
        save_btn = QPushButton("Salvar")
        save_btn.clicked.connect(self._on_save)
        reset_btn = QPushButton("Restaurar padrões")
        reset_btn.clicked.connect(self._on_reset)
        actions.addWidget(save_btn)
        actions.addWidget(reset_btn)
        actions.addStretch()
        outer.addLayout(actions)

        outer.addStretch()

        footer = QLabel(f"Arquivo: <code>{settings_file()}</code>")
        footer.setStyleSheet("color: #666;")
        footer.setTextInteractionFlags(footer.textInteractionFlags())
        outer.addWidget(footer)

        self._refresh_fields()

    def _refresh_fields(self) -> None:
        self._claude_cmd.setText(self.settings.claude_command)
        self._claude_args.setText(" ".join(shlex.quote(a) for a in self.settings.claude_extra_args))
        self._terminal_cmd.setText(self.settings.terminal_command)
        self._vscode_cmd.setText(self.settings.vscode_command)
        self._intellij_cmd.setText(self.settings.intellij_command)
        self._webstorm_cmd.setText(self.settings.webstorm_command)
        self._pycharm_cmd.setText(self.settings.pycharm_command)
        self._rider_cmd.setText(self.settings.rider_command)

    def _on_save(self) -> None:
        self.settings.claude_command = self._claude_cmd.text().strip() or "claude"
        try:
            self.settings.claude_extra_args = shlex.split(self._claude_args.text())
        except ValueError as e:
            QMessageBox.warning(self, "Args inválidos", f"Não consegui parsear: {e}")
            return
        self.settings.terminal_command = self._terminal_cmd.text().strip() or "konsole"
        self.settings.vscode_command = self._vscode_cmd.text().strip() or "code"
        self.settings.intellij_command = self._intellij_cmd.text().strip() or "idea"
        self.settings.webstorm_command = self._webstorm_cmd.text().strip() or "webstorm"
        self.settings.pycharm_command = self._pycharm_cmd.text().strip() or "pycharm"
        self.settings.rider_command = self._rider_cmd.text().strip() or "rider"

        try:
            self.settings.save()
        except OSError as e:
            QMessageBox.critical(self, "Erro ao salvar", str(e))
            return

        self.settings_saved.emit()
        QMessageBox.information(self, "Configurações salvas", "Pronto, configurações atualizadas.")

    def _on_reset(self) -> None:
        defaults = Settings()
        self.settings.update_from(defaults)
        self._refresh_fields()
