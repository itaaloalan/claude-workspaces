from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..mcp_manager import set_postgres_mcp


class MCPDialog(QDialog):
    """Edita/cria o MCP postgres do workspace. Nome do MCP = nome do
    workspace; usuário só fornece a URL postgres."""

    def __init__(
        self,
        workspace_name: str,
        current_url: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.workspace_name = workspace_name
        action = "Editar" if current_url else "Criar"
        self.setWindowTitle(f"{action} MCP — {workspace_name}")
        self.resize(540, 200)

        outer = QVBoxLayout(self)

        intro = QLabel(
            f"MCP <code>{workspace_name}</code> (postgres) — fornece acesso "
            "ao banco pelo Claude. O Claude executa <code>npx -y "
            "@modelcontextprotocol/server-postgres &lt;url&gt;</code> quando "
            "esse workspace abre uma sessão."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #aaa;")
        outer.addWidget(intro)

        form = QFormLayout()
        self.url_edit = QLineEdit(current_url)
        self.url_edit.setPlaceholderText(
            "postgresql://user:senha@localhost:5432/database"
        )
        form.addRow("URL postgres:", self.url_edit)
        outer.addLayout(form)

        hint = QLabel(
            "Dica: pode copiar a URL do seu pgAdmin/DBeaver ou montar como "
            "<code>postgresql://postgres:qwe123@localhost:5432/nome_do_banco</code>."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666; font-size: 11px;")
        outer.addWidget(hint)

        outer.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _save(self) -> None:
        url = self.url_edit.text().strip()
        try:
            set_postgres_mcp(self.workspace_name, url)
        except ValueError as e:
            QMessageBox.warning(self, "URL inválida", str(e))
            return
        except OSError as e:
            QMessageBox.critical(self, "Erro ao salvar", str(e))
            return
        self.accept()
