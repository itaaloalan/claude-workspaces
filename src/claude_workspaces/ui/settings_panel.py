import logging
import shlex

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
        # NotificationService é injetado depois (MainWindow chama
        # `set_notification_service`); até lá os controles do center
        # ficam ocultos.
        self._notif_service = None

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

        self._file_open_cmd = QLineEdit()
        self._file_open_cmd.setPlaceholderText("code")
        self._file_open_cmd.setToolTip(
            "Comando do menu de contexto 'Abrir/editar arquivo' no painel "
            "Arquivos. Aceita args, ex.: 'code -r', 'subl', 'gedit'."
        )
        form.addRow("Abrir arquivo com:", self._file_open_cmd)

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

        outer.addWidget(self._build_claude_section())
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
        self._set_combo_value(
            self._claude_permission_mode,
            self._permission_mode_choices,
            self.settings.claude_permission_mode,
        )
        self._set_combo_value(
            self._claude_model, self._model_choices, self.settings.claude_model
        )
        self._set_combo_value(
            self._claude_effort, self._effort_choices, self.settings.claude_effort
        )
        self._claude_allowed_tools.setText(self.settings.claude_allowed_tools)
        self._claude_disallowed_tools.setText(self.settings.claude_disallowed_tools)
        self._terminal_cmd.setText(self.settings.terminal_command)
        self._shell_cmd.setText(self.settings.shell_command)
        self._vscode_cmd.setText(self.settings.vscode_command)
        self._file_open_cmd.setText(self.settings.file_open_command)
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
        self._discord_enabled_chk.setChecked(self.settings.discord_webhook_enabled)
        self._discord_webhook_url.setText(self.settings.discord_webhook_url)

    def _on_discord_test(self) -> None:
        url = self._discord_webhook_url.text().strip()
        if not url:
            QMessageBox.warning(
                self, "Webhook vazio", "Cole a URL do webhook antes de testar."
            )
            return
        from ..notifications.discord import build_embed_payload, send_webhook
        from ..notifications import NotificationPriority

        payload = build_embed_payload(
            title="✅ Teste do Claude Workspaces",
            body="Webhook configurado com sucesso — as notificações chegarão aqui.",
            priority=NotificationPriority.NORMAL,
            workspace=self.settings.notify_app_name or "Claude Workspaces",
        )
        ok, msg = send_webhook(url, payload)
        if ok:
            QMessageBox.information(
                self, "Webhook OK", f"Mensagem de teste enviada ({msg})."
            )
        else:
            QMessageBox.critical(
                self, "Falha no webhook", f"Não consegui enviar:\n{msg}"
            )

    def _on_save(self) -> None:
        self.settings.claude_command = self._claude_cmd.text().strip() or "claude"
        try:
            self.settings.claude_extra_args = shlex.split(self._claude_args.text())
        except ValueError as e:
            QMessageBox.warning(self, "Args inválidos", f"Não consegui parsear: {e}")
            return
        self.settings.claude_permission_mode = self._get_combo_value(
            self._claude_permission_mode, self._permission_mode_choices
        )
        self.settings.claude_model = self._get_combo_value(
            self._claude_model, self._model_choices
        )
        self.settings.claude_effort = self._get_combo_value(
            self._claude_effort, self._effort_choices
        )
        self.settings.claude_allowed_tools = self._claude_allowed_tools.text().strip()
        self.settings.claude_disallowed_tools = self._claude_disallowed_tools.text().strip()
        self.settings.terminal_command = self._terminal_cmd.text().strip() or "konsole"
        self.settings.shell_command = self._shell_cmd.text().strip()
        self.settings.vscode_command = self._vscode_cmd.text().strip() or "code"
        self.settings.file_open_command = self._file_open_cmd.text().strip() or "code"
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
        self.settings.discord_webhook_enabled = self._discord_enabled_chk.isChecked()
        self.settings.discord_webhook_url = self._discord_webhook_url.text().strip()

        try:
            self.settings.save()
        except OSError as e:
            QMessageBox.critical(self, "Erro ao salvar", str(e))
            return

        self.settings_saved.emit()
        from .persistent_toast import flash_toast
        flash_toast("Configurações salvas")

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

    def _build_claude_section(self) -> QWidget:
        box = QGroupBox("Claude — defaults da sessão")
        layout = QVBoxLayout(box)

        intro = QLabel(
            "Estas opções viram flags do <code>claude</code> CLI em toda "
            "sessão lançada pelo app (console embutido, terminal externo, "
            "resume, runner-gen). Você ainda pode trocar modo/modelo/effort "
            "depois — Shift+Tab cicla o modo e <code>/model</code> "
            "<code>/effort</code> trocam dentro da sessão."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        self._claude_permission_mode = QComboBox()
        self._claude_permission_mode.setEditable(False)
        self._permission_mode_choices: list[tuple[str, str]] = [
            ("", "(default do Claude)"),
            ("default", "default — pergunta a cada edição"),
            ("acceptEdits", "acceptEdits — edita sem pedir"),
            ("plan", "plan — planeja antes de editar"),
            ("auto", "auto — escolhe o modo por tarefa"),
            ("bypassPermissions", "bypassPermissions — sem perguntas"),
            ("dontAsk", "dontAsk — bypass silencioso"),
        ]
        for _val, label in self._permission_mode_choices:
            self._claude_permission_mode.addItem(label)
        self._claude_permission_mode.setToolTip(
            "Equivalente a --permission-mode <mode> no claude CLI. Vazio = "
            "não passa a flag (Claude usa seu default global)."
        )
        form.addRow("Modo inicial:", self._claude_permission_mode)

        self._claude_model = QComboBox()
        self._claude_model.setEditable(True)
        self._model_choices: list[tuple[str, str]] = [
            ("", "(default do Claude)"),
            ("opus", "opus — mais capaz"),
            ("sonnet", "sonnet — equilibrado"),
            ("haiku", "haiku — mais rápido/barato"),
        ]
        for _val, label in self._model_choices:
            self._claude_model.addItem(label)
        self._claude_model.setToolTip(
            "Equivalente a --model <id> no claude CLI. Aceita alias "
            "(opus/sonnet/haiku) ou nome completo (ex.: claude-sonnet-4-6). "
            "Edite o campo pra digitar um ID específico."
        )
        form.addRow("Modelo padrão:", self._claude_model)

        self._claude_effort = QComboBox()
        self._claude_effort.setEditable(False)
        self._effort_choices: list[tuple[str, str]] = [
            ("", "(default do Claude)"),
            ("low", "low"),
            ("medium", "medium"),
            ("high", "high"),
            ("xhigh", "xhigh"),
            ("max", "max"),
        ]
        for _val, label in self._effort_choices:
            self._claude_effort.addItem(label)
        self._claude_effort.setToolTip(
            "Equivalente a --effort <level> no claude CLI."
        )
        form.addRow("Effort padrão:", self._claude_effort)

        self._claude_allowed_tools = QLineEdit()
        self._claude_allowed_tools.setPlaceholderText('ex: "Bash(git *) Edit Read"')
        self._claude_allowed_tools.setToolTip(
            "Lista (separada por espaço ou vírgula) de tool specs liberadas. "
            "Vira --allowedTools no claude CLI."
        )
        form.addRow("Tools permitidas:", self._claude_allowed_tools)

        self._claude_disallowed_tools = QLineEdit()
        self._claude_disallowed_tools.setPlaceholderText('ex: "Bash(rm *) WebFetch"')
        self._claude_disallowed_tools.setToolTip(
            "Lista de tool specs bloqueadas. Vira --disallowedTools no claude CLI."
        )
        form.addRow("Tools bloqueadas:", self._claude_disallowed_tools)

        layout.addLayout(form)
        return box

    @staticmethod
    def _set_combo_value(
        combo: QComboBox, choices: list[tuple[str, str]], value: str
    ) -> None:
        for idx, (val, _label) in enumerate(choices):
            if val == value:
                combo.setCurrentIndex(idx)
                return
        if combo.isEditable() and value:
            combo.setCurrentText(value)
        else:
            combo.setCurrentIndex(0)

    @staticmethod
    def _get_combo_value(
        combo: QComboBox, choices: list[tuple[str, str]]
    ) -> str:
        idx = combo.currentIndex()
        if 0 <= idx < len(choices):
            preset_val, preset_label = choices[idx]
            if combo.isEditable():
                typed = combo.currentText().strip()
                if typed and typed != preset_label:
                    return typed
            return preset_val
        if combo.isEditable():
            return combo.currentText().strip()
        return ""

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
        self._notify_ready_prefix.setPlaceholderText("⏳ Aguardando")
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

        # --------------- Discord (webhook) ---------------
        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>Discord</b>"))
        dc_intro = QLabel(
            "Espelha cada notificação da central num canal do Discord. Crie um "
            "webhook em <i>Configurações do canal → Integrações → Webhooks</i> e "
            "cole a URL (formato <code>https://discord.com/api/webhooks/&lt;id&gt;/"
            "&lt;token&gt;</code>). Os mutes por tipo da central também valem aqui."
        )
        dc_intro.setWordWrap(True)
        dc_intro.setStyleSheet("color: #c8c8c8;")
        layout.addWidget(dc_intro)

        self._discord_enabled_chk = QCheckBox(
            "Enviar notificações para o webhook do Discord"
        )
        layout.addWidget(self._discord_enabled_chk)

        dc_form = QFormLayout()
        self._discord_webhook_url = QLineEdit()
        self._discord_webhook_url.setPlaceholderText(
            "https://discord.com/api/webhooks/..."
        )
        self._discord_webhook_url.setToolTip(
            "URL completa do webhook do canal. Fica salva em settings.json."
        )
        dc_form.addRow("URL do webhook:", self._discord_webhook_url)
        layout.addLayout(dc_form)

        dc_row = QHBoxLayout()
        self._discord_test_btn = QPushButton("Testar webhook")
        self._discord_test_btn.setToolTip(
            "Envia uma mensagem de teste pra URL preenchida acima."
        )
        self._discord_test_btn.clicked.connect(self._on_discord_test)
        dc_row.addWidget(self._discord_test_btn)
        dc_row.addStretch()
        layout.addLayout(dc_row)

        # --------------- Centro de Notificações (novo) ---------------
        # Preferências persistidas em notifications.json (NotificationService),
        # separado das settings tradicionais — granularidade por tipo /
        # workspace, limite de histórico, limpar histórico.
        layout.addSpacing(10)
        self._notif_center_section = QWidget()
        sec_layout = QVBoxLayout(self._notif_center_section)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        sec_layout.setSpacing(6)
        sec_layout.addWidget(QLabel("<b>Centro de Notificações</b>"))
        sec_intro = QLabel(
            "Controla o sino, a inbox e os toasts do desktop. As preferências "
            "são salvas em <code>~/.config/claude-workspaces/notifications.json</code>."
        )
        sec_intro.setWordWrap(True)
        sec_intro.setStyleSheet("color: #c8c8c8;")
        sec_layout.addWidget(sec_intro)

        self._notif_desktop_chk = QCheckBox(
            "Mostrar toasts do desktop (D-Bus)"
        )
        self._notif_desktop_chk.setToolTip(
            "Quando desligado, novas notificações ainda contam no sino e "
            "aparecem na inbox, mas nenhum popup nativo é disparado."
        )
        sec_layout.addWidget(self._notif_desktop_chk)

        # Mute por tipo — uma checkbox por kind.
        from ..notifications import NotificationKind as _Kind
        self._notif_kind_chks: dict[str, QCheckBox] = {}
        kind_labels = {
            _Kind.PERMISSION_REQUIRED: "Pedidos de permissão",
            _Kind.AGENT_WAITING: "Agente aguardando",
            _Kind.TASK_COMPLETED: "Tarefa concluída",
            _Kind.TASK_FAILED: "Tarefa falhou",
            _Kind.AGENT_IDLE: "Agente ocioso",
            _Kind.LONG_RUNNING: "Execução longa",
            _Kind.COST_WARNING: "Aviso de custo",
            _Kind.WORKSPACE_ERROR: "Erro no workspace",
        }
        mute_box = QGroupBox("Silenciar por tipo")
        mute_layout = QVBoxLayout(mute_box)
        for kind, label in kind_labels.items():
            chk = QCheckBox(label)
            self._notif_kind_chks[kind] = chk
            mute_layout.addWidget(chk)
        sec_layout.addWidget(mute_box)

        # Histórico
        hist_form = QFormLayout()
        self._notif_history_limit = QSpinBox()
        self._notif_history_limit.setRange(50, 5000)
        self._notif_history_limit.setSingleStep(50)
        self._notif_history_limit.setToolTip(
            "Quantas notificações guardar em disco (mais antigas são descartadas)."
        )
        hist_form.addRow("Histórico máximo:", self._notif_history_limit)
        sec_layout.addLayout(hist_form)

        row_clear = QHBoxLayout()
        self._notif_clear_btn = QPushButton("Limpar histórico")
        self._notif_clear_btn.setToolTip(
            "Remove notificações já vistas/descartadas. Pendentes ficam."
        )
        self._notif_clear_btn.clicked.connect(self._on_notif_clear_history)
        row_clear.addWidget(self._notif_clear_btn)
        row_clear.addStretch()
        sec_layout.addLayout(row_clear)

        # Hooks salvar/carregar valores quando o service estiver setado.
        self._notif_desktop_chk.toggled.connect(self._on_notif_pref_changed)
        for chk in self._notif_kind_chks.values():
            chk.toggled.connect(self._on_notif_pref_changed)
        self._notif_history_limit.valueChanged.connect(self._on_notif_pref_changed)

        # Esconde até o service ser injetado.
        self._notif_center_section.setVisible(False)
        layout.addWidget(self._notif_center_section)

        self._refresh_hook_status()
        return box

    def set_notification_service(self, service) -> None:
        """MainWindow injeta o `NotificationService` depois da construção,
        ativando a sub-seção 'Centro de Notificações' e carregando os
        valores atuais. Idempotente — pode ser chamado de novo se as
        preferências forem alteradas externamente."""
        self._notif_service = service
        prefs = service.preferences
        # Carrega valores sem disparar callbacks (block signals).
        self._notif_desktop_chk.blockSignals(True)
        self._notif_desktop_chk.setChecked(bool(prefs.get("desktop_enabled", True)))
        self._notif_desktop_chk.blockSignals(False)
        muted = set(prefs.get("muted_kinds") or [])
        for kind, chk in self._notif_kind_chks.items():
            chk.blockSignals(True)
            chk.setChecked(kind in muted)
            chk.blockSignals(False)
        self._notif_history_limit.blockSignals(True)
        self._notif_history_limit.setValue(int(prefs.get("history_limit", 500)))
        self._notif_history_limit.blockSignals(False)
        self._notif_center_section.setVisible(True)

    def _on_notif_pref_changed(self, *_args) -> None:
        if self._notif_service is None:
            return
        muted = [
            kind for kind, chk in self._notif_kind_chks.items() if chk.isChecked()
        ]
        self._notif_service.set_preferences(
            desktop_enabled=self._notif_desktop_chk.isChecked(),
            muted_kinds=muted,
            history_limit=int(self._notif_history_limit.value()),
        )

    def _on_notif_clear_history(self) -> None:
        if self._notif_service is None:
            return
        removed = self._notif_service.clear_dismissed()
        for n in self._notif_service.list():
            if n.seen and not n.is_actionable():
                self._notif_service.remove(n.id)
                removed += 1
        log.info("Limpou %s notificações do histórico", removed)

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
