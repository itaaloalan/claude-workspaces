import logging
import shlex

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..hook_manager import (
    claude_settings_file,
    install_hook,
    is_hook_installed,
    uninstall_hook,
)
from ..logging_setup import log_file
from ..settings import Settings, settings_file

log = logging.getLogger(__name__)


class SettingsPanel(QWidget):
    settings_saved = Signal()

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._workspace_getter = None

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
        intro.setStyleSheet("color: #c8c8c8;")
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

        self._shell_cmd = QLineEdit()
        self._shell_cmd.setPlaceholderText("(vazio = shell de login do /etc/passwd)")
        self._shell_cmd.setToolTip(
            "Shell usado pra rodar Claude/terminal interativo. Vazio = autodetectar "
            "o shell de login do usuário (fish/zsh/bash). Aliases do shell são "
            "carregados porque rodamos com -i."
        )
        form.addRow("Shell:", self._shell_cmd)

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

        self._browser_cmd = QLineEdit()
        self._browser_cmd.setPlaceholderText("(vazio = xdg-open / browser do sistema)")
        self._browser_cmd.setToolTip(
            "Comando usado pelo 'Abrir browser ao carregar' dos runners. "
            "Vazio = QDesktopServices.openUrl (xdg-open no Linux). Aceita "
            "binário no PATH ('chromium', 'firefox') ou caminho absoluto."
        )
        form.addRow("Browser:", self._browser_cmd)

        self._browser_delay_ms = QSpinBox()
        self._browser_delay_ms.setRange(0, 60000)
        self._browser_delay_ms.setSingleStep(500)
        self._browser_delay_ms.setSuffix(" ms")
        self._browser_delay_ms.setToolTip(
            "Delay entre detectar a URL pronta e abrir o browser. "
            "Alguns servers logam a URL antes de aceitar conexões — esse "
            "delay evita ECONNREFUSED. Default 5000ms."
        )
        form.addRow("Delay p/ abrir browser:", self._browser_delay_ms)

        outer.addLayout(form)

        outer.addWidget(self._build_worktree_section())
        outer.addWidget(self._build_notifications_section())
        outer.addWidget(self._build_status_detection_section())
        outer.addWidget(self._build_inspectors_section())

        actions = QHBoxLayout()
        save_btn = QPushButton("Salvar")
        save_btn.clicked.connect(self._on_save)
        reset_btn = QPushButton("Restaurar padrões")
        reset_btn.clicked.connect(self._on_reset)
        actions.addWidget(save_btn)
        actions.addWidget(reset_btn)
        actions.addStretch()
        open_log_btn = QPushButton("Abrir log")
        open_log_btn.setToolTip(f"Abre {log_file()}")
        open_log_btn.clicked.connect(self._open_log)
        actions.addWidget(open_log_btn)
        outer.addLayout(actions)

        outer.addStretch()

        footer = QLabel(
            f"Configurações: <code>{settings_file()}</code><br>"
            f"Logs: <code>{log_file()}</code>"
        )
        footer.setStyleSheet("color: #999;")
        footer.setTextInteractionFlags(footer.textInteractionFlags())
        outer.addWidget(footer)

        self._refresh_fields()

    def _refresh_fields(self) -> None:
        self._claude_cmd.setText(self.settings.claude_command)
        self._claude_args.setText(" ".join(shlex.quote(a) for a in self.settings.claude_extra_args))
        self._terminal_cmd.setText(self.settings.terminal_command)
        self._shell_cmd.setText(self.settings.shell_command)
        self._vscode_cmd.setText(self.settings.vscode_command)
        self._intellij_cmd.setText(self.settings.intellij_command)
        self._webstorm_cmd.setText(self.settings.webstorm_command)
        self._pycharm_cmd.setText(self.settings.pycharm_command)
        self._rider_cmd.setText(self.settings.rider_command)
        self._browser_cmd.setText(self.settings.browser_command)
        self._browser_delay_ms.setValue(int(self.settings.browser_open_delay_ms))
        self._default_isolate_chk.setChecked(self.settings.default_isolate_worktree)
        self._default_new_branch_chk.setChecked(self.settings.default_create_new_branch)
        self._branch_prefix.setText(self.settings.branch_prefix)
        self._notify_native_chk.setChecked(self.settings.notify_native_enabled)
        self._notify_sound_chk.setChecked(self.settings.notify_sound_enabled)
        self._notify_sound_name.setText(self.settings.notify_sound_name)
        self._notify_timeout_ms.setValue(int(self.settings.notify_timeout_ms))
        self._notify_reminder_chk.setChecked(self.settings.notify_reminder_enabled)
        self._notify_reminder_secs.setValue(self.settings.notify_reminder_seconds)
        self._notify_app_name.setText(self.settings.notify_app_name)
        self._notify_ready_prefix.setText(self.settings.notify_ready_prefix)
        self._notify_decision_prefix.setText(self.settings.notify_decision_prefix)
        self._notify_reminder_prefix.setText(self.settings.notify_reminder_prefix)
        self._notify_hook_title_fmt.setText(self.settings.notify_hook_title_format)
        self._notify_hook_default_body.setText(self.settings.notify_hook_default_body)
        self._idle_debounce_secs.setValue(self.settings.idle_debounce_seconds)

    def _on_save(self) -> None:
        self.settings.claude_command = self._claude_cmd.text().strip() or "claude"
        try:
            self.settings.claude_extra_args = shlex.split(self._claude_args.text())
        except ValueError as e:
            QMessageBox.warning(self, "Args inválidos", f"Não consegui parsear: {e}")
            return
        self.settings.terminal_command = self._terminal_cmd.text().strip() or "konsole"
        self.settings.shell_command = self._shell_cmd.text().strip()
        self.settings.vscode_command = self._vscode_cmd.text().strip() or "code"
        self.settings.intellij_command = self._intellij_cmd.text().strip() or "idea"
        self.settings.webstorm_command = self._webstorm_cmd.text().strip() or "webstorm"
        self.settings.pycharm_command = self._pycharm_cmd.text().strip() or "pycharm"
        self.settings.rider_command = self._rider_cmd.text().strip() or "rider"
        self.settings.browser_command = self._browser_cmd.text().strip()
        self.settings.browser_open_delay_ms = int(self._browser_delay_ms.value())
        self.settings.default_isolate_worktree = self._default_isolate_chk.isChecked()
        self.settings.default_create_new_branch = self._default_new_branch_chk.isChecked()
        self.settings.branch_prefix = (
            self._branch_prefix.text().strip().strip("/") or "claude"
        )
        self.settings.notify_native_enabled = self._notify_native_chk.isChecked()
        self.settings.notify_sound_enabled = self._notify_sound_chk.isChecked()
        self.settings.notify_sound_name = self._notify_sound_name.text().strip()
        self.settings.notify_timeout_ms = int(self._notify_timeout_ms.value())
        self.settings.notify_reminder_enabled = self._notify_reminder_chk.isChecked()
        self.settings.notify_reminder_seconds = int(self._notify_reminder_secs.value())
        self.settings.notify_app_name = (
            self._notify_app_name.text().strip() or "Claude Workspaces"
        )
        self.settings.notify_ready_prefix = self._notify_ready_prefix.text()
        self.settings.notify_decision_prefix = self._notify_decision_prefix.text()
        self.settings.notify_reminder_prefix = self._notify_reminder_prefix.text()
        self.settings.notify_hook_title_format = (
            self._notify_hook_title_fmt.text().strip() or "Claude — {project}"
        )
        self.settings.notify_hook_default_body = (
            self._notify_hook_default_body.text().strip() or "(turno encerrado)"
        )
        self.settings.idle_debounce_seconds = int(self._idle_debounce_secs.value())

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

    def _open_log(self) -> None:
        path = log_file()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _build_worktree_section(self) -> QWidget:
        box = QGroupBox("Worktree / Git ao abrir Claude")
        layout = QVBoxLayout(box)

        intro = QLabel(
            "Pré-marca essas opções no diálogo 'Abrir Claude'. Você pode "
            "sempre desmarcar antes de confirmar."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(intro)

        self._default_isolate_chk = QCheckBox(
            "Isolar em git worktree por padrão"
        )
        layout.addWidget(self._default_isolate_chk)

        self._default_new_branch_chk = QCheckBox(
            "Criar nova branch por padrão (quando isolar)"
        )
        layout.addWidget(self._default_new_branch_chk)

        form = QFormLayout()
        self._branch_prefix = QLineEdit()
        self._branch_prefix.setPlaceholderText("claude")
        self._branch_prefix.setToolTip(
            "Prefixo das branches sugeridas pelo worktree. Resulta em "
            "<prefixo>/<timestamp> (ex: italo/20260515-180000)."
        )
        form.addRow("Prefixo da branch:", self._branch_prefix)
        layout.addLayout(form)

        return box

    def _build_notifications_section(self) -> QWidget:
        box = QGroupBox("Notificações")
        layout = QVBoxLayout(box)

        intro = QLabel(
            "Quando ativado, o Claude dispara uma notificação do desktop a "
            "cada turno encerrado, mostrando o nome do projeto e a tarefa. "
            f"Mexe em <code>{claude_settings_file()}</code> preservando seus "
            "outros hooks."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(intro)

        self._hook_status = QLabel()
        layout.addWidget(self._hook_status)

        row = QHBoxLayout()
        self._hook_toggle_btn = QPushButton()
        self._hook_toggle_btn.clicked.connect(self._toggle_hook)
        row.addWidget(self._hook_toggle_btn)
        row.addStretch()
        layout.addLayout(row)

        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>Re-lembretes</b>"))

        re_intro = QLabel(
            "Se uma tarefa termina e você não voltou pra aba, o app reavisa "
            "no intervalo abaixo. No menu do sino 🔔 você pode adiar (snooze) "
            "ou marcar como \"já vi — não me lembre\" pra silenciar essa "
            "entrada específica."
        )
        re_intro.setWordWrap(True)
        re_intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(re_intro)

        self._notify_native_chk = QCheckBox(
            "Mostrar notificação nativa (toast/tray) ao final de cada tarefa"
        )
        layout.addWidget(self._notify_native_chk)

        self._notify_sound_chk = QCheckBox(
            "Tocar som nas notificações nativas"
        )
        self._notify_sound_chk.setToolTip(
            "Usa a hint sound-name do D-Bus — o servidor de notificações "
            "(KDE/GNOME/dunst) toca o sample correspondente do tema."
        )
        layout.addWidget(self._notify_sound_chk)

        sound_form = QFormLayout()
        self._notify_sound_name = QLineEdit()
        self._notify_sound_name.setPlaceholderText("message-new-instant")
        self._notify_sound_name.setToolTip(
            "Nome XDG do som (ex: message-new-instant, message, complete, "
            "bell, alarm-clock-elapsed). Vazio = sem som."
        )
        sound_form.addRow("Nome do som:", self._notify_sound_name)
        layout.addLayout(sound_form)

        timeout_form = QFormLayout()
        self._notify_timeout_ms = QSpinBox()
        self._notify_timeout_ms.setRange(-1, 600000)
        self._notify_timeout_ms.setSingleStep(1000)
        self._notify_timeout_ms.setSuffix(" ms")
        self._notify_timeout_ms.setToolTip(
            "Tempo de exibição do banner. -1 = default do SO "
            "(respeita KDE/GNOME); 0 = sticky (não some sozinho); "
            ">0 = força esse tempo em ms. Default 10000 (10s)."
        )
        timeout_form.addRow("Duração do banner:", self._notify_timeout_ms)
        layout.addLayout(timeout_form)

        self._notify_reminder_chk = QCheckBox(
            "Reavisar tarefas paradas sem foco"
        )
        layout.addWidget(self._notify_reminder_chk)

        re_form = QFormLayout()
        self._notify_reminder_secs = QSpinBox()
        self._notify_reminder_secs.setRange(15, 3600)
        self._notify_reminder_secs.setSingleStep(15)
        self._notify_reminder_secs.setSuffix(" s")
        self._notify_reminder_secs.setToolTip(
            "Tempo entre re-lembretes. Mínimo 15s, máximo 1h."
        )
        re_form.addRow("Reavisar a cada:", self._notify_reminder_secs)
        layout.addLayout(re_form)

        layout.addSpacing(8)
        layout.addWidget(QLabel("<b>Textos das notificações</b>"))

        texts_intro = QLabel(
            "Personalize o rótulo do app e os títulos/corpo das notificações. "
            "Use string vazia nos prefixos pra esconder. No template do hook, "
            "<code>{project}</code> é substituído pelo basename do cwd."
        )
        texts_intro.setWordWrap(True)
        texts_intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(texts_intro)

        texts_form = QFormLayout()

        self._notify_app_name = QLineEdit()
        self._notify_app_name.setPlaceholderText("Claude Workspaces")
        self._notify_app_name.setToolTip(
            "Rótulo do app no banner (D-Bus app_name / tray tooltip / notify-send -a)."
        )
        texts_form.addRow("Nome do app:", self._notify_app_name)

        self._notify_ready_prefix = QLineEdit()
        self._notify_ready_prefix.setPlaceholderText("✅ Pronto")
        self._notify_ready_prefix.setToolTip(
            "Prefixo do título quando uma tarefa termina (formato: '<prefixo> — <workspace>')."
        )
        texts_form.addRow("Prefixo 'pronto':", self._notify_ready_prefix)

        self._notify_decision_prefix = QLineEdit()
        self._notify_decision_prefix.setPlaceholderText("❓ Decisão")
        self._notify_decision_prefix.setToolTip(
            "Prefixo do título quando o Claude abre um picker/permission prompt "
            "(formato: '<prefixo> — <workspace>')."
        )
        texts_form.addRow("Prefixo 'decisão':", self._notify_decision_prefix)

        self._notify_reminder_prefix = QLineEdit()
        self._notify_reminder_prefix.setPlaceholderText("🔁 Ainda aguardando")
        self._notify_reminder_prefix.setToolTip(
            "Prefixo do título nos re-lembretes (formato: '<prefixo> — <workspace>')."
        )
        texts_form.addRow("Prefixo re-lembrete:", self._notify_reminder_prefix)

        self._notify_hook_title_fmt = QLineEdit()
        self._notify_hook_title_fmt.setPlaceholderText("Claude — {project}")
        self._notify_hook_title_fmt.setToolTip(
            "Template do título do hook Stop. {project} = basename do cwd."
        )
        texts_form.addRow("Título do hook:", self._notify_hook_title_fmt)

        self._notify_hook_default_body = QLineEdit()
        self._notify_hook_default_body.setPlaceholderText("(turno encerrado)")
        self._notify_hook_default_body.setToolTip(
            "Body do hook quando não dá pra ler a última mensagem do usuário do transcript."
        )
        texts_form.addRow("Body padrão do hook:", self._notify_hook_default_body)

        layout.addLayout(texts_form)

        self._refresh_hook_status()
        return box

    def _build_status_detection_section(self) -> QWidget:
        box = QGroupBox("Detecção de status")
        layout = QVBoxLayout(box)

        intro = QLabel(
            "Enquanto o Claude responde, o parser de status oscila entre "
            "<b>Trabalhando</b> e <b>Ocioso</b> (cada tool call ou pausa "
            "entre tokens parece ociosidade momentânea). O app só vira "
            '"Ocioso" depois de N segundos estáveis sem voltar a trabalhar, '
            "pra evitar flicker na sidebar. <i>0 desliga o debounce</i> "
            "(comportamento antigo, com flicker)."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(intro)

        form = QFormLayout()
        self._idle_debounce_secs = QSpinBox()
        self._idle_debounce_secs.setRange(0, 120)
        self._idle_debounce_secs.setSingleStep(1)
        self._idle_debounce_secs.setSuffix(" s")
        self._idle_debounce_secs.setToolTip(
            "Quanto tempo esperar antes de marcar o terminal como 'Ocioso' "
            "depois que o parser detecta fim de turno. 0–120s. Padrão: 20s."
        )
        form.addRow("Esperar antes de mostrar 'Ocioso':", self._idle_debounce_secs)
        layout.addLayout(form)

        return box

    def _build_inspectors_section(self) -> QWidget:
        box = QGroupBox("Inspetores")
        layout = QVBoxLayout(box)
        intro = QLabel(
            "Ferramentas read-only pra entender o estado do Claude no "
            "workspace atual."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(intro)

        row = QHBoxLayout()
        hooks_btn = QPushButton("🪝 Inspetor de hooks…")
        hooks_btn.setToolTip("Hooks de Stop/PostToolUse/etc por escopo")
        hooks_btn.clicked.connect(self._open_hooks_inspector)
        row.addWidget(hooks_btn)
        mcp_btn = QPushButton("🔌 Explorer de MCP…")
        mcp_btn.setToolTip(
            "Lista servidores MCP configurados em ~/.claude.json e .mcp.json"
        )
        mcp_btn.clicked.connect(self._open_mcp_explorer)
        row.addWidget(mcp_btn)
        row.addStretch()
        layout.addLayout(row)
        return box

    def _open_hooks_inspector(self) -> None:
        from .hooks_inspector_dialog import HooksInspectorDialog
        ws = self._workspace_getter() if self._workspace_getter else None
        dlg = HooksInspectorDialog(ws, parent=self)
        dlg.show()

    def _open_mcp_explorer(self) -> None:
        from .mcp_explorer_dialog import McpExplorerDialog
        ws = self._workspace_getter() if self._workspace_getter else None
        dlg = McpExplorerDialog(ws, parent=self)
        dlg.show()

    def set_workspace_getter(self, getter) -> None:
        """MainWindow injeta um callable que retorna o workspace ativo,
        pra que o inspector enxergue hooks do projeto selecionado."""
        self._workspace_getter = getter

    def _refresh_hook_status(self) -> None:
        if is_hook_installed():
            self._hook_status.setText(
                "✓ Hook instalado — Claude notifica ao fim de cada turno"
            )
            self._hook_status.setStyleSheet("color: #5ac35a;")
            self._hook_toggle_btn.setText("Remover notificações")
        else:
            self._hook_status.setText("Hook não instalado — notificações desativadas")
            self._hook_status.setStyleSheet("color: #b0b0b0;")
            self._hook_toggle_btn.setText("Ativar notificações")

    def _toggle_hook(self) -> None:
        try:
            if is_hook_installed():
                uninstall_hook()
            else:
                install_hook()
        except Exception as e:
            log.exception("Falha ao alternar hook")
            QMessageBox.warning(self, "Erro com hook", str(e))
            return
        self._refresh_hook_status()
