from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)


SHORTCUTS = [
    ("Workspaces", [
        ("Ctrl+N", "Criar novo workspace"),
        ("Ctrl+1 … Ctrl+9", "Pular pro N-ésimo workspace visível"),
        ("Ctrl+Tab / Ctrl+Shift+Tab", "Próximo / anterior workspace"),
        ("Ctrl+F", "Focar a busca no topbar"),
        ("Ctrl+Enter", "Abrir Claude no workspace atual"),
        ("Ctrl+,", "Configurações"),
    ]),
    ("Layout", [
        ("Ctrl+B", "Esconder / mostrar barra lateral"),
        ("Ctrl+J", "Esconder / mostrar terminal"),
        ("Ctrl+Shift+B", "Esconder / mostrar dock direito"),
    ]),
    ("Terminal", [
        ("Ctrl+T", "Nova aba de shell"),
        ("Ctrl+Shift+W", "Fechar aba ativa"),
        ("Ctrl+K", "Limpar terminal ativo"),
        ("Ctrl+Alt+←  /  Ctrl+Alt+→", "Aba anterior / próxima"),
    ]),
    ("Arquivos", [
        ("Ctrl+P", "Quick open: arquivos do workspace (em breve)"),
        ("Ctrl+O", "Abrir pasta primária no gerenciador de arquivos"),
        ("Ctrl+Shift+C", "Copiar caminho da pasta primária"),
    ]),
    ("Ajuda", [
        ("Ctrl+/", "Mostrar este diálogo"),
    ]),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atalhos de teclado — Claude Workspaces")
        self.resize(620, 540)

        outer = QVBoxLayout(self)
        outer.setSpacing(12)

        title = QLabel("<h2 style='margin:0;'>Atalhos de teclado</h2>")
        outer.addWidget(title)

        hint = QLabel(
            "Pressionar dentro da janela do app. Os atalhos do terminal "
            "embutido (Ctrl+T, Ctrl+K…) operam no terminal visível."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #b0b0b0;")
        outer.addWidget(hint)

        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)

        for section, items in SHORTCUTS:
            sec_label = QLabel(f"<b>{section}</b>")
            sec_label.setStyleSheet("margin-top: 4px;")
            outer.addWidget(sec_label)
            for key, desc in items:
                row = QHBoxLayout()
                row.setContentsMargins(8, 0, 0, 0)
                k = QLabel(key)
                k.setFont(mono)
                k.setMinimumWidth(220)
                k.setStyleSheet("color: #6aa9e0;")
                row.addWidget(k)
                d = QLabel(desc)
                d.setWordWrap(True)
                d.setStyleSheet("color: #d0d0d0;")
                row.addWidget(d, stretch=1)
                outer.addLayout(row)

        outer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        outer.addWidget(buttons)
