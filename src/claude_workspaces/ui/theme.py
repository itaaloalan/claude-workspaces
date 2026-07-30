"""Paleta única e helpers de QSS pra reduzir CSS hardcoded em 15 arquivos.

Não troca todos os usos de uma vez — extração progressiva. Cada widget
novo deve consumir essas constantes; widgets antigos serão migrados
conforme tocarmos eles. Veja MAINTAINABILITY.md item #4.
"""

# ---------- Paleta ----------
# Dark neutro (estilo Orca): cinzas puros quase pretos, bordas 1 nível
# acima do fundo, "accent" claro em vez de cor forte. Cores saturadas
# ficam reservadas a semântica (git/status/PR).

BG_DEEP = "#0e0e0e"        # áreas do terminal (mais escuro)
BG_DARKEST = "#111111"     # fundo dock
BG_DARKER = "#131313"      # topbar, headers compactos
BG_DARK = "#161616"        # listas, plain text edits
BG_PANEL = "#181818"       # background geral de painéis
BG_SURFACE = "#1e1e1e"     # botões neutros, inputs
BG_ELEVATED = "#232323"    # menus, popovers, cards em destaque

BORDER = "#262626"         # divisores, splitter handles
BORDER_SOFT = "#1f1f1f"    # borda em listas (item separator)
BORDER_INPUT = "#2b2b2b"   # borda de inputs/buttons

PRIMARY = "#e6e6e6"        # "accent" neutro claro: botão primário, foco
PRIMARY_HOVER = "#f2f2f2"
PRIMARY_PRESSED = "#d9d9d9"
PRIMARY_HOVER_BG = "#222222"  # hover suave em listas
TEXT_ON_ACCENT = "#111111"    # texto sobre bg PRIMARY (claro)
PRIMARY_SELECTION_BG = "rgba(255, 255, 255, 26)"  # bg de item selecionado (~10% branco)

TEXT_PRIMARY = "#e6e6e6"    # texto principal
TEXT_BRIGHT = "#ffffff"     # texto sobre seleção (usar pouco)
TEXT_MUTED = "#b8b8b8"      # texto secundário
TEXT_FADED = "#9a9a9a"      # contadores, hints, status
TEXT_FAINT = "#757575"      # placeholders, labels de seção
TEXT_DISABLED = "#4f4f4f"
TEXT_LINK = "#cfcfcf"       # links / hover de botão flat

SUCCESS = "#6fbf73"         # verde (concluído, adicionado)
WARNING = "#d6b95c"         # amarelo (trabalhando, modificado)
DANGER = "#cf6f6f"          # vermelho (deletado, erro)
INFO = "#6f9fd8"            # azul claro (renomeado, info) — semântico
WAITING = "#cc8b57"         # laranja (aguardando atenção, inbox)
WAITING_HOVER = "#dd9a63"
WAITING_BG = "#9c6a3c"      # bg do bell quando há inbox
PLANNING = "#5fb3af"        # teal — planejando (plan mode)
PR_PINK = "#d67ba8"         # rosa — PR detectado, estado desconhecido
PR_PINK_BG = "rgba(214, 123, 168, 0.12)"  # fundo do banner de PR

# Estados de PR/MR (paleta GitHub adaptada ao dark do app)
PR_OPEN = "#6fbf73"         # verde — PR/MR aberto
PR_DRAFT = "#8f8f8f"        # cinza — draft
PR_MERGED = "#a586d9"       # roxo — merged
PR_CLOSED = "#cf6f6f"       # vermelho — fechado sem merge


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
    """Splitter invisível em repouso — só aparece no hover/drag."""
    return (
        "QSplitter::handle { background: transparent; }"
        "QSplitter::handle:hover { background: #333333; }"
        "QSplitter::handle:pressed { background: #3a3a3a; }"
    )


def primary_button_qss() -> str:
    """Botão claro com texto escuro — reservado a UMA ação por tela."""
    return (
        f"QPushButton {{"
        f"  background: {PRIMARY}; color: {TEXT_ON_ACCENT};"
        f"  border: 0; border-radius: {RADIUS_MD}px; padding: 6px 14px;"
        f"  font-weight: 600;"
        f"}}"
        f"QPushButton:hover {{ background: {PRIMARY_HOVER}; }}"
        f"QPushButton:disabled {{ background: {BORDER}; color: {TEXT_DISABLED}; }}"
    )


def neutral_button_qss() -> str:
    """Ghost button — o padrão do app: transparente com borda sutil;
    hover clareia com overlay em vez de trocar pra cor de accent."""
    return (
        f"QPushButton {{"
        f"  background: transparent; color: {TEXT_MUTED};"
        f"  border: 1px solid {BORDER}; border-radius: {RADIUS_MD}px;"
        f"  padding: 6px 12px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: rgba(255, 255, 255, 15); color: {TEXT_PRIMARY};"
        f"}}"
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
        f"  background: {PRIMARY}; color: {TEXT_ON_ACCENT}; border-color: {PRIMARY};"
        f"}}"
    )


def list_widget_qss() -> str:
    return (
        f"QListWidget {{"
        f"  background: {BG_DARK}; border: 1px solid {BORDER_INPUT};"
        f"  border-radius: 6px; color: {TEXT_PRIMARY};"
        f"}}"
        f"QListWidget::item {{"
        f"  padding: 8px 8px;"
        f"  color: {TEXT_MUTED};"
        f"}}"
        f"QListWidget::item:hover {{ background: {PRIMARY_HOVER_BG}; color: {TEXT_BRIGHT}; }}"
        f"QListWidget::item:selected {{ background: {PRIMARY_SELECTION_BG}; color: {TEXT_BRIGHT}; }}"
        f"QListWidget::item:selected:hover {{ background: rgba(255, 255, 255, 36); color: {TEXT_BRIGHT}; }}"
    )


# ---------- Spacing / radius scale ----------

SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 8
SPACE_LG = 12
SPACE_XL = 16
SPACE_XXL = 24

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8


# ---------- Escala tipográfica (px, pra QSS) ----------

FONT_XS = 10   # badges, pills
FONT_SM = 11   # metadados, headers de seção
FONT_MD = 12   # corpo compacto
FONT_LG = 14   # títulos de painel


# ---------- Estados (sessão / item) ----------
# Cor sólida que vai na barra lateral do card + cor do texto do badge.
# bg do badge = state @ ~15% via state_badge_qss().

STATE_WORKING = WARNING     # âmbar — Claude trabalhando
STATE_AWAITING = WAITING    # laranja — aguardando permissão / atenção
STATE_IDLE = TEXT_FAINT     # cinza — ocioso
STATE_ERROR = DANGER        # vermelho — erro
STATE_DONE = SUCCESS        # verde — concluído


_STATE_BADGE_BG = {
    STATE_WORKING: "rgba(214, 185, 92, 38)",
    STATE_AWAITING: "rgba(204, 139, 87, 46)",
    STATE_IDLE: "rgba(117, 117, 117, 32)",
    STATE_ERROR: "rgba(207, 111, 111, 42)",
    STATE_DONE: "rgba(111, 191, 115, 38)",
    PLANNING: "rgba(95, 179, 175, 38)",
}


def section_header_qss() -> str:
    """Label de header de seção (sm-caps, faint, letter-spacing)."""
    return (
        f"QLabel {{"
        f"  color: {TEXT_FAINT};"
        f"  font-size: {FONT_SM}px;"
        f"  font-weight: 600;"
        f"  letter-spacing: 0.5px;"
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


def pr_chip_qss(color: str) -> str:
    """Chip compacto de PR/MR — cor sólida no texto, mesma cor a ~12%
    de alpha no fundo. Generaliza o chip rosa original pra qualquer
    estado (aberto/draft/merged/fechado)."""
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return (
        f"QLabel {{"
        f" background: rgba({r}, {g}, {b}, 0.12);"
        f" color: {color};"
        f" font-size: 9px; font-weight: 700;"
        f" padding: 1px 5px; border-radius: 6px;"
        f" border: 0;"
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
    poluir com badge grande. Sem borda ao redor (borda completa criava
    poluição visual quando muitos cards estão listados)."""
    bg = bg or BG_SURFACE
    return (
        f"QFrame#{object_name} {{"
        f"  background: {bg};"
        f"  border: 0;"
        f"  border-left: 2px solid {state_color};"
        f"  border-radius: {radius}px;"
        f"}}"
    )


# ---------- Tema do terminal (xterm.js) ----------
# Fonte única de verdade pro visual do console/runners — empurrado pro JS
# via TerminalBridge.theme_changed (JSON) no frontend_ready. Os valores
# hardcoded em terminal.html/terminal.js são só fallback anti-flash e
# devem espelhar estes.

TERMINAL_FONT_SIZE = 13
TERMINAL_FONT_FAMILY = (
    '"JetBrains Mono", "Hack", "Fira Code", "DejaVu Sans Mono", monospace'
)

def terminal_theme() -> dict:
    """Tema do xterm.js + CSS vars do terminal.html.

    De propósito NÃO define a paleta ANSI 16: o conteúdo do terminal
    (TUI do Claude, ls --color, logs) fica com as cores vivas default do
    xterm.js — uma paleta dessaturada aqui deixava tudo com cara de
    "desabilitado/acinzentado". O neutro do redesign vale só pro chrome
    (fundo/cursor/seleção/scrollbar)."""
    return {
        "fontSize": TERMINAL_FONT_SIZE,
        "fontFamily": TERMINAL_FONT_FAMILY,
        "xterm": {
            "background": BG_DEEP,
            "foreground": "#e6e6e6",
            "cursor": PRIMARY,
            "cursorAccent": BG_DEEP,
            "selectionBackground": "#2e2e2e",
        },
        "css": {
            "--term-bg": BG_DEEP,
            "--scroll-thumb": "rgba(255, 255, 255, 0.10)",
            "--scroll-thumb-hover": "rgba(255, 255, 255, 0.40)",
        },
    }


def tree_widget_qss() -> str:
    return (
        f"QTreeWidget {{ background: transparent; border: 0; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item {{ padding: 4px 4px; color: {TEXT_PRIMARY}; }}"
        f"QTreeWidget::item:hover {{ background: {PRIMARY_HOVER_BG}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected {{ background: {PRIMARY_SELECTION_BG}; color: {TEXT_BRIGHT}; }}"
        f"QTreeWidget::item:selected:hover {{ background: rgba(255, 255, 255, 36); color: {TEXT_BRIGHT}; }}"
    )
