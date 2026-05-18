"""RunnerEditDialog — cria ou edita um RunnerConfig."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import RunnerConfig


class RunnerEditDialog(QDialog):
    """Dialog modal pra editar nome + comandos do runner.

    Não persiste sozinho — quem chama deve usar `result_runner()` se
    `exec()` retornar Accepted e atualizar o workspace.
    """

    def __init__(
        self,
        runner: RunnerConfig | None,
        on_generate_with_claude=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar Runner" if runner else "Novo Runner")
        self.resize(620, 480)

        self._original = runner
        base = runner or RunnerConfig()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)

        self._name = QLineEdit(base.name)
        self._name.setPlaceholderText("ex: web, api, glassfish")
        form.addRow("Nome:", self._name)

        self._cwd = QLineEdit(base.cwd)
        self._cwd.setPlaceholderText("(vazio → primeira pasta do workspace)")
        form.addRow("cwd:", self._cwd)

        self._start = QPlainTextEdit(base.start_cmd)
        self._start.setPlaceholderText("ex: npm run dev")
        self._start.setFixedHeight(70)
        form.addRow("Start:", self._start)

        self._stop = QPlainTextEdit(base.stop_cmd)
        self._stop.setPlaceholderText("(opcional — vazio = SIGHUP no processo)")
        self._stop.setFixedHeight(60)
        form.addRow("Stop:", self._stop)

        self._restart = QPlainTextEdit(base.restart_cmd)
        self._restart.setPlaceholderText("(opcional — vazio = stop + start)")
        self._restart.setFixedHeight(60)
        form.addRow("Restart:", self._restart)

        self._enabled = QCheckBox("Incluir em 'Rodar todos'")
        self._enabled.setChecked(base.enabled)
        form.addRow("", self._enabled)

        self._open_browser = QCheckBox("Abrir browser ao carregar")
        self._open_browser.setToolTip(
            "Detecta a URL/porta na saída do start_cmd e abre no browser "
            "padrão (ou no comando configurado em Configurações). Abre "
            "uma vez por start."
        )
        self._open_browser.setChecked(base.open_browser_on_ready)
        form.addRow("", self._open_browser)

        self._browser_url = QLineEdit(base.browser_url)
        self._browser_url.setPlaceholderText(
            "(opcional — vazio = detectar a URL na saída do processo)"
        )
        form.addRow("URL do browser:", self._browser_url)

        layout.addLayout(form)

        if on_generate_with_claude is not None:
            gen_btn = QPushButton("✨ Gerar com Claude")
            gen_btn.setToolTip(
                "Abre o Claude no contexto do claude-workspaces pra gerar os "
                "comandos deste runner. Você copia o JSON e cola nos campos."
            )
            gen_btn.clicked.connect(on_generate_with_claude)
            layout.addWidget(gen_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_runner(self) -> RunnerConfig:
        """Devolve o RunnerConfig final. Preserva o id quando editando."""
        base = self._original
        return RunnerConfig(
            id=base.id if base else RunnerConfig().id,
            name=self._name.text().strip() or "runner",
            cwd=self._cwd.text().strip(),
            start_cmd=self._start.toPlainText().strip(),
            stop_cmd=self._stop.toPlainText().strip(),
            restart_cmd=self._restart.toPlainText().strip(),
            enabled=self._enabled.isChecked(),
            open_browser_on_ready=self._open_browser.isChecked(),
            browser_url=self._browser_url.text().strip(),
            env=(base.env if base else {}),
        )
