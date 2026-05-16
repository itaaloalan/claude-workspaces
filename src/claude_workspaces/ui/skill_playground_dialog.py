"""Playground pra testar uma skill/agente/comando sem mexer no workspace.

Usa `claude --print` (non-interactive) com um prompt isolado. Mostra o
output em tempo real numa área de texto. Sem efeito colateral nos
arquivos do projeto — usuário pode iterar no design antes de versionar.

Limitações:
- A skill/agente PRECISA estar instalada num escopo visível (user ou
  projeto) — playground não injeta o conteúdo do .md, só invoca por nome.
- Não suporta tool_use real (Read/Write/Bash etc): o run usa
  `--allowed-tools` vazio por padrão pra evitar I/O acidental.
"""

import logging
import shlex

from PySide6.QtCore import QProcess
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..settings import Settings
from ..skills_discovery import KIND_COMMAND, KIND_SKILL, ClaudeItem

log = logging.getLogger(__name__)


def _suggested_prompt(item: ClaudeItem) -> str:
    """Prompt inicial dependendo do tipo."""
    if item.kind == KIND_SKILL:
        return f"/{item.name}\n\n# digite aqui um teste curto do que essa skill faz"
    if item.kind == KIND_COMMAND:
        return f"/{item.name}\n\n# argumentos do comando aqui"
    # Agent
    return (
        f"Use o subagent '{item.name}' para executar a tarefa abaixo "
        f"(ele deve detectar isso automaticamente):\n\n"
        f"# descreva a tarefa de teste aqui"
    )


class SkillPlaygroundDialog(QDialog):
    def __init__(
        self,
        item: ClaudeItem,
        settings: Settings,
        cwd: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Playground: {item.invocation}")
        self.resize(900, 700)
        self.setModal(False)
        self._item = item
        self._settings = settings
        self._cwd = cwd
        self._process: QProcess | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        header = QLabel(
            f"<b>{item.kind.title()}</b> · "
            f"<code>{item.invocation}</code> · "
            f"fonte: <code>{item.source_label}</code>"
        )
        outer.addWidget(header)

        hint = QLabel(
            "Rodar este teste invoca <code>claude --print</code> com "
            "<code>--allowed-tools=\"\"</code> (sem I/O) — output só. "
            "Pra liberar tools, ajuste o campo abaixo."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b0b0b0;")
        outer.addWidget(hint)

        # Prompt
        outer.addWidget(QLabel("<b>Prompt:</b>"))
        self._prompt = QPlainTextEdit()
        self._prompt.setPlainText(_suggested_prompt(item))
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._prompt.setFont(font)
        self._prompt.setMaximumHeight(180)
        outer.addWidget(self._prompt)

        # Allowed-tools
        tools_row = QHBoxLayout()
        tools_row.addWidget(QLabel("Allowed tools (vírgula, vazio = nenhuma):"))
        self._tools_edit = QLineEdit()
        self._tools_edit.setPlaceholderText("Read, Grep   (default: nenhuma)")
        tools_row.addWidget(self._tools_edit, stretch=1)
        outer.addLayout(tools_row)

        # Run controls
        run_row = QHBoxLayout()
        self._run_btn = QPushButton("▶ Rodar")
        self._run_btn.clicked.connect(self._run)
        run_row.addWidget(self._run_btn)
        self._cancel_btn = QPushButton("⏹ Parar")
        self._cancel_btn.clicked.connect(self._stop)
        self._cancel_btn.setEnabled(False)
        run_row.addWidget(self._cancel_btn)
        clear_btn = QPushButton("🗑 Limpar output")
        clear_btn.clicked.connect(lambda: self._output.clear())
        run_row.addWidget(clear_btn)
        run_row.addStretch()
        self._status = QLabel("idle")
        self._status.setStyleSheet("color: #888;")
        run_row.addWidget(self._status)
        outer.addLayout(run_row)

        # Output
        outer.addWidget(QLabel("<b>Output:</b>"))
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(font)
        self._output.setPlaceholderText("(saída aparecerá aqui)")
        outer.addWidget(self._output, stretch=1)

        # Footer
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)

    def _build_argv(self, prompt: str, allowed_tools: str) -> list[str]:
        """Argv pra rodar `claude --print` com o prompt + restrições."""
        claude = (self._settings.claude_command or "claude").strip()
        argv = shlex.split(claude)
        argv.append("--print")
        # Permission mode bypass se tools forem permitidas; senão zero I/O
        if allowed_tools.strip():
            argv.append("--allowed-tools")
            argv.append(allowed_tools.strip())
        else:
            argv.append("--allowed-tools")
            argv.append("")  # nenhuma tool
        argv.append(prompt)
        return argv

    def _run(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            return
        prompt = self._prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Prompt vazio", "Digite algo no prompt.")
            return
        argv = self._build_argv(prompt, self._tools_edit.text())
        log.info("Playground run: %s", argv)

        self._output.clear()
        self._output.appendPlainText(f"$ {' '.join(shlex.quote(a) for a in argv)}\n")
        self._status.setText("running…")
        self._status.setStyleSheet("color: #e6a23c;")
        self._run_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if self._cwd:
            self._process.setWorkingDirectory(self._cwd)
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        program, *args = argv
        self._process.start(program, args)

    def _on_stdout(self) -> None:
        if not self._process:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )
        self._output.moveCursor(self._output.textCursor().MoveOperation.End)
        self._output.insertPlainText(chunk)
        self._output.moveCursor(self._output.textCursor().MoveOperation.End)

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        self._status.setText(f"exited {exit_code}")
        self._status.setStyleSheet(
            "color: #5ac35a;" if exit_code == 0 else "color: #e74c3c;"
        )
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    def _on_error(self, err) -> None:
        msg = self._process.errorString() if self._process else str(err)
        self._output.appendPlainText(f"\n[QProcess error] {msg}")
        self._status.setText("error")
        self._status.setStyleSheet("color: #e74c3c;")
        self._run_btn.setEnabled(True)
        self._cancel_btn.setEnabled(False)

    def _stop(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._output.appendPlainText("\n[interrompido pelo usuário]")
            self._status.setText("killed")
            self._status.setStyleSheet("color: #e74c3c;")
            self._run_btn.setEnabled(True)
            self._cancel_btn.setEnabled(False)

    def closeEvent(self, event) -> None:
        self._stop()
        super().closeEvent(event)
