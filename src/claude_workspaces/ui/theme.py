"""Paleta única e helpers de QSS pra reduzir CSS hardcoded em 15 arquivos.

Não troca todos os usos de uma vez — extração progressiva. Cada widget
novo deve consumir essas constantes; widgets antigos serão migrados
conforme tocarmos eles. Veja MAINTAINABILITY.md item #4.
"""

# ---------- Paleta ----------

BG_DEEP = "#0e0e0e"        # áreas do terminal (mais escuro)
BG_DARKEST = "#141414"     # fundo dock
BG_DARKER = "#161616"      # topbar, headers compactos
BG_DARK = "#181818"        # listas, plain text edits
BG_PANEL = "#1a1a1a"       # background geral de painéis
BG_SURFACE = "#1f1f1f"     # botões neutros, inputs

BORDER = "#2a2a2a"         # divisores, splitter handles
BORDER_SOFT = "#232323"    # borda em listas (item separator)
BORDER_INPUT = "#2c2c2c"   # borda de inputs/buttons

PRIMARY = "#3d6ea8"        # azul de seleção / botão primário
PRIMARY_HOVER = "#4a82c5"
PRIMARY_PRESSED = "#5a92d5"
PRIMARY_HOVER_BG = "#2a3142"  # hover suave em listas (azul-escuro)

TEXT_PRIMARY = "#e6e6e6"    # texto principal
TEXT_BRIGHT = "#ffffff"     # texto sobre seleção
TEXT_MUTED = "#c8c8c8"      # texto secundário
TEXT_FADED = "#b0b0b0"      # contadores, hints, status
TEXT_FAINT = "#888888"      # placeholders, labels de seção
TEXT_DISABLED = "#555555"
TEXT_LINK = "#6aa9e0"       # links / hover de botão flat

SUCCESS = "#5ac35a"         # verde (concluído, adicionado)
WARNING = "#e0b86a"         # amber (trabalhando, modificado)
DANGER = "#d57272"          # vermelho (deletado, erro)
INFO = "#7aa6e6"            # azul claro (renomeado, info)
WAITING = "#e09060"         # laranja (aguardando atenção, inbox)
WAITING_HOVER = "#e0892f"
WAITING_BG = "#c9772d"      # bg do bell quando há inbox


# ---------- Helpers de QSS ----------

def splitter_qss() -> str:
    return (
        f"QSplitter::handle {{ background: {BORDER}; }}"
        f"QSplitter::handle:hover {{ background: {PRIMARY}; }}"
        f"QSplitter::handle:pressed {{ background: {PRIMARY_HOVER}; }}"
    )


def primary_button_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: {PRIMARY}; color: {TEXT_BRIGHT};"
        f"  border: 0; border-radius: 4px; padding: 4px 14px; font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background: {PRIMARY_HOVER}; }}"
        f"QPushButton:disabled {{ background: {BORDER}; color: {TEXT_DISABLED}; }}"
    )


def neutral_button_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: {BG_SURFACE}; color: {TEXT_PRIMARY};"
        f"  border: 1px solid {BORDER_INPUT}; border-radius: 6px;"
        f"  padding: 6px 12px;"
        f"}}"
        f"QPushButton:hover {{ border-color: {PRIMARY}; color: {TEXT_LINK}; }}"
    )


def flat_icon_button_qss() -> str:
    """Botão flat tipo toolbar — sem borda no estado normal."""
    return (
        f"QPushButton {{"
        f"  background: transparent; color: {TEXT_MUTED};"
        f"  border: 1px solid transparent; border-radius: 4px;"
        f"  padding: 2px 8px;"
        f"}}"
        f"QPushButton:hover {{ color: {TEXT_LINK}; border-color: {PRIMARY}; }}"
        f"QPushButton:disabled {{ color: {TEXT_DISABLED}; }}"
    )


def line_edit_qss() -> str:
    return (
        f"QLineEdit {{"
        f"  background: {BG_SURFACE}; border: 1px solid {BORDER_INPUT};"
        f"  border-radius: 4px; padding: 4px 8px; color: {TEXT_PRIMARY};"
        f"}}"
        f"QLineEdit:focus {{ border-color: {PRIMARY}; }}"
    )


def chip_button_qss() -> str:
    return (
        f"QPushButton {{"
        f"  background: transparent; color: {TEXT_MUTED};"
        f"  border: 1px solid {BORDER_INPUT}; border-radius: 12px;"
        f"  padding: 2px 10px; font-size: 11px;"
        f"}}"
        f"QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {PRIMARY}; }}"
        f"QPushButton:checked {{"
        f"  background: {PRIMARY}; color: {TEXT_BRIGHT}; border-color: {PRIMARY};"
        f"}}"
    )


def list_widget_qss() -> str:
    return (
        f"QListWidget {{"
        f"  background: {BG_DARK}; border: 1px solid {BORDER_INPUT};"
        f"  border-radius: 6px; color: {TEXT_PRIMARY};"
        f"}}"
        f"QListWidget::item {{"
        f"  padding: 6px 8px; border-bottom: 1px solid {BORDER_SOFT};"
        f"  color: {TEXT_MUTED};"
        f"}}"
        f"QListWidget::item:hover {{ background: {PRIMARY_HOVER_BG}; color: {TEXT_BRIGHT}; }}"
        f"QListWidget::item:selected {{ background: {PRIMARY}; color: {TEXT_BRIGHT}; }}"
        f"QListWidget::item:selected:hover {{ background: {PRIMARY_HOVER}; color: {TEXT_BRIGHT}; }}"
    )


def tree_widget_qss() -> str:
    return (
        f"QTreeWidget {{ background: transparent; border: 0; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item {{ padding: 4px 4px; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item:hover {{ background: {PRIMARY_HOVER_BG}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected {{ background: {PRIMARY}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected:hover {{ background: {PRIMARY_HOVER}; color: {TEXT_BRIGHT}; }}"
    )
