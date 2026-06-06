"""RunnerEditDialog — cria ou edita um RunnerConfig."""

from __future__ import annotations

import shlex
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..models import RunnerConfig

_NPM_LIKE = {"npm", "yarn", "pnpm", "bun", "npx"}


def _detect_script_file(start_cmd: str, cwd: str) -> Path | None:
    """Heurística pra achar o arquivo do script invocado pelo start_cmd.

    - `npm start`, `yarn dev`, `pnpm run X` → `<cwd>/package.json`
    - `bash foo.sh`, `sh foo.sh`, `python foo.py`, `node foo.js` → o arquivo
    - `./foo.sh`, `bin/foo` → o próprio token
    Devolve None se nada plausível for encontrado.
    """
    cmd = (start_cmd or "").strip()
    if not cmd:
        return None
    base = Path(cwd).expanduser() if cwd else Path.cwd()

    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    if not tokens:
        return None

    first = Path(tokens[0]).name
    if first in _NPM_LIKE:
        pkg = base / "package.json"
        return pkg if pkg.exists() else None

    interpreters = {"bash", "sh", "zsh", "fish", "python", "python3", "node", "deno", "ruby", "perl"}
    if first in interpreters:
        for tok in tokens[1:]:
            if tok.startswith("-"):
                continue
            cand = (base / tok).expanduser()
            if cand.exists() and cand.is_file():
                return cand
            return None

    cand = (base / tokens[0]).expanduser()
    if cand.exists() and cand.is_file():
        return cand
    return None


class RunnerEditDialog(QDialog):
    """Dialog modal pra editar nome + comandos do runner.

    Não persiste sozinho — quem chama deve usar `result_runner()` se
    `exec()` retornar Accepted e atualizar o workspace.
    """

    def __init__(
        self,
        runner: RunnerConfig | None,
        on_generate_with_claude=None,
        on_resume_gen=None,
        on_edit_with_claude=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_edit_with_claude = on_edit_with_claude
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
        start_wrap = QWidget()
        start_layout = QVBoxLayout(start_wrap)
        start_layout.setContentsMargins(0, 0, 0, 0)
        start_layout.setSpacing(4)
        start_layout.addWidget(self._start)
        edit_row = QHBoxLayout()
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.addStretch(1)
        self._edit_script_btn = QPushButton("📝 Editar script")
        self._edit_script_btn.setToolTip(
            "Abre o arquivo de script referenciado pelo start_cmd no editor "
            "padrão do sistema (package.json para npm/yarn/pnpm; arquivo "
            "direto para bash/python/node etc)."
        )
        self._edit_script_btn.clicked.connect(self._on_edit_script)
        edit_row.addWidget(self._edit_script_btn)
        start_layout.addLayout(edit_row)
        form.addRow("Start:", start_wrap)

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

        self._include_stack = QCheckBox("Incluir no '⬇ Subir stack' (cópia pro console)")
        self._include_stack.setChecked(base.include_in_stack)
        self._include_stack.setToolTip(
            "Quando marcado, o '⬇ Subir stack' copia este runner pro "
            "console (com porta remapeada e cwd do worktree). Desmarque "
            "runners que não fazem parte da stack paralela (ex: no map, "
            "só web + api sobem; jdk8/history/coletor ficam de fora). "
            "A cópia manual via '↗ Copiar do workspace' ignora esta flag."
        )
        form.addRow("", self._include_stack)

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

        self._ready_pattern = QLineEdit(base.ready_pattern)
        self._ready_pattern.setPlaceholderText(
            "(opcional — regex que precisa casar antes do browser abrir)"
        )
        self._ready_pattern.setToolTip(
            "Regex case-insensitive aplicado na stdout. Quando preenchido, "
            "o browser só abre depois que esse padrão aparece no log — "
            "útil pra Glassfish/Tomcat, onde a porta sobe antes do "
            "deploy terminar. Ex: 'Application \\[ogpms\\] deployed' ou '>>> ready:'."
        )
        form.addRow("Padrão de pronto:", self._ready_pattern)

        self._port = QSpinBox()
        self._port.setRange(0, 65535)
        self._port.setValue(base.port)
        self._port.setSpecialValueText("(sem porta)")
        self._port.setToolTip(
            "Porta base do runner. Use {port} no Start/Stop/Restart, na URL "
            "do browser e nos valores do env — é substituído por este número "
            "na hora de rodar. {port:<nome>} resolve a porta de OUTRO runner "
            "do mesmo escopo (ex: web referenciando {port:api}). O app também "
            "injeta PORT e SERVER_PORT no ambiente (a menos que você os "
            "defina no env) e aplica --port automaticamente em dev servers "
            "conhecidos (ng/vite/next/npm). Cópias deste runner para "
            "consoles/worktrees ganham automaticamente a próxima porta livre "
            "(base+1, base+2…). 0 = sem porta."
        )
        form.addRow("Porta base:", self._port)

        layout.addLayout(form)

        # Editando um runner existente → IA ajusta SÓ este runner, recebendo
        # a config atual + erro recente. Criando um novo → IA investiga o
        # workspace e gera do zero.
        if runner is not None and on_edit_with_claude is not None:
            edit_ai_btn = QPushButton("✨ Editar com IA")
            edit_ai_btn.setToolTip(
                "Abre o agente com a config atual deste runner + a saída/erro "
                "recente dele e pede um ajuste. A IA salva um rascunho; "
                "feche este dialog e clique em 'Recarregar' pra aplicar."
            )
            edit_ai_btn.clicked.connect(self._on_edit_with_claude_clicked)
            layout.addWidget(edit_ai_btn)
        elif on_generate_with_claude is not None:
            gen_btn = QPushButton("✨ Gerar com IA")
            gen_btn.setToolTip(
                "Abre o agente no contexto do claude-workspaces pra gerar os "
                "comandos deste runner. Você copia o JSON e cola nos campos."
            )
            gen_btn.clicked.connect(on_generate_with_claude)
            layout.addWidget(gen_btn)

        # Botão pra retomar a sessão IA que originou este runner.
        # Só aparece quando estamos editando (runner != None) e há
        # metadata de geração persistida.
        if (
            on_resume_gen is not None
            and runner is not None
            and runner.gen_session_id
            and runner.gen_cwd
        ):
            resume_btn = QPushButton("↻ Retomar geração com IA")
            resume_btn.setToolTip(
                "Reabre via `claude --resume` a sessão que gerou este runner — "
                "use pra pedir ajustes sem perder o contexto da conversa."
            )
            sid = runner.gen_session_id
            cwd = runner.gen_cwd
            resume_btn.clicked.connect(
                lambda _checked=False, s=sid, c=cwd: on_resume_gen(s, c)
            )
            layout.addWidget(resume_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_edit_with_claude_clicked(self) -> None:
        # Manda os valores ATUAIS do dialog (não só o original) — assim o
        # Claude edita o que o usuário está vendo. Fecha o dialog em seguida
        # pra liberar o acesso ao botão "Recarregar" (dialog é modal).
        if self._on_edit_with_claude is None:
            return
        self._on_edit_with_claude(self.result_runner())
        self.reject()

    def _on_edit_script(self) -> None:
        start_cmd = self._start.toPlainText().strip()
        cwd = self._cwd.text().strip()
        target = _detect_script_file(start_cmd, cwd)
        if target is None:
            QMessageBox.information(
                self,
                "Editar script",
                "Não consegui detectar o arquivo do script a partir do "
                "comando.\n\nSuportado: npm/yarn/pnpm/bun (abre package.json), "
                "bash/sh/python/node + arquivo, ou caminho direto pra um "
                "script (ex.: ./run.sh).\n\nVerifique também se o cwd está "
                "preenchido corretamente.",
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

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
            include_in_stack=self._include_stack.isChecked(),
            open_browser_on_ready=self._open_browser.isChecked(),
            browser_url=self._browser_url.text().strip(),
            ready_pattern=self._ready_pattern.text().strip(),
            port=self._port.value(),
            env=(base.env if base else {}),
        )
