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


# ---------- Tempos (ms) ----------

LAYOUT_SAVE_DEBOUNCE_MS = 600   # debounce pra persistir splitter/geometry
SPINNER_INTERVAL_MS = 100       # tick do spinner ⠋⠙⠹…
AUTOSAVE_INTERVAL_MS = 3000     # autosave de editor inline (CLAUDE.md)
GIT_POLL_INTERVAL_MS = 30_000   # polling do painel git
REMINDER_TICK_MS = 5_000        # tick do timer de re-lembrete da inbox


# ---------- Dimensões (px) ----------

SPLITTER_HANDLE_W = 8           # largura dos handles dos QSplitter
SIDEBAR_DEFAULT_W = 260         # largura padrão da sidebar
SIDEBAR_FALLBACK_W = 240
RIGHT_DOCK_DEFAULT_W = 340
RIGHT_DOCK_FALLBACK_W = 340
RIGHT_SPLIT_TERMINAL_DEFAULT_H = 520
RIGHT_SPLIT_CONTENT_DEFAULT_H = 380
TERMINAL_HEADER_MIN_H = 28      # altura mínima do header do terminal minimizado
TERMINAL_BTN_W = 28             # largura fixa dos botões min/max/restore


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


# ---------- Spacing / radius scale ----------

SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 8
SPACE_LG = 12

RADIUS_SM = 4
RADIUS_MD = 6


# ---------- Estados (sessão / item) ----------
# Cor sólida que vai na barra lateral do card + cor do texto do badge.
# bg do badge = state @ ~15% via state_badge_qss().

STATE_WORKING = WARNING     # âmbar — Claude trabalhando
STATE_AWAITING = WAITING    # laranja — aguardando permissão / atenção
STATE_IDLE = TEXT_FAINT     # cinza — ocioso
STATE_ERROR = DANGER        # vermelho — erro
STATE_DONE = SUCCESS        # verde — concluído


_STATE_BADGE_BG = {
    STATE_WORKING: "rgba(224, 184, 106, 38)",
    STATE_AWAITING: "rgba(224, 144, 96, 46)",
    STATE_IDLE: "rgba(136, 136, 136, 32)",
    STATE_ERROR: "rgba(213, 114, 114, 42)",
    STATE_DONE: "rgba(90, 195, 90, 38)",
}


def section_header_qss() -> str:
    """Label de header de seção (sm-caps, faint, letter-spacing)."""
    return (
        f"QLabel {{"
        f"  color: {TEXT_FAINT};"
        f"  font-size: 10px;"
        f"  font-weight: 700;"
        f"  letter-spacing: 1.4px;"
        f"  padding: 2px 4px 6px 4px;"
        f"}}"
    )


def state_badge_qss(state_color: str) -> str:
    """Pill compacto pra status (Trabalhando/Aguardando/etc)."""
    bg = _STATE_BADGE_BG.get(state_color, "rgba(136, 136, 136, 32)")
    return (
        f"QLabel {{"
        f"  background: {bg};"
        f"  color: {state_color};"
        f"  font-size: 9px;"
        f"  font-weight: 700;"
        f"  padding: 1px 7px;"
        f"  border-radius: 8px;"
        f"}}"
    )


def left_accent_qss(
    state_color: str,
    *,
    bg: str | None = None,
    border: str | None = None,
    radius: int = RADIUS_MD,
    object_name: str = "AccentCard",
) -> str:
    """Card com barra colorida de 3px à esquerda — sinaliza estado sem
    poluir com badge grande. O resto do card mantém bg/borda padrão."""
    bg = bg or BG_SURFACE
    border = border or BORDER_INPUT
    return (
        f"QFrame#{object_name} {{"
        f"  background: {bg};"
        f"  border: 1px solid {border};"
        f"  border-left: 3px solid {state_color};"
        f"  border-radius: {radius}px;"
        f"}}"
    )


def tree_widget_qss() -> str:
    return (
        f"QTreeWidget {{ background: transparent; border: 0; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item {{ padding: 4px 4px; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item:hover {{ background: {PRIMARY_HOVER_BG}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected {{ background: {PRIMARY}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected:hover {{ background: {PRIMARY_HOVER}; color: {TEXT_BRIGHT}; }}"
    )
