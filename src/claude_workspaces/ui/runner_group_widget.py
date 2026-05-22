"""Header widget pro grupo "Runners" na sidebar.

Aparece como item filho do workspace (ou do console) quando há ao menos
um runner naquele escopo. Os RunnerChildWidget ficam aninhados sob ele,
então o usuário pode recolher tudo de uma vez pela seta da tree.

    [Runners workspace]                              [＋]

O botão ＋ abre o diálogo de criação de runner no escopo correto.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from . import theme


_BTN_QSS = (
    f"QPushButton {{"
    f"  background: transparent;"
    f"  color: {theme.TEXT_FAINT};"
    f"  border: 0;"
    f"  border-radius: 4px;"
    f"  padding: 0px 4px;"
    f"  font-size: 12px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: {theme.BG_SURFACE};"
    f"  color: {theme.TEXT_LINK};"
    f"}}"
)


class RunnerGroupWidget(QWidget):
    """Linha de header pro grupo colapsável de runners."""

    def __init__(
        self,
        label: str,
        on_add_blank: Callable[[], None],
        on_generate: Callable[[], None] | None = None,
        on_toggle_collapse: Callable[[], None] | None = None,
        on_stop_all: Callable[[], None] | None = None,
        on_restart_all: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(24)
        self.setMaximumHeight(26)

        row = QHBoxLayout(self)
        # Margens/spacing iguais ao header do bucket "Sessões Claude" pra os
        # dois grupos ficarem alinhados verticalmente na sidebar.
        row.setContentsMargins(4, 2, 6, 2)
        row.setSpacing(6)

        from PySide6.QtCore import QSize as _QS
        from .icons import ic as _ic

        # Chevron como QLabel pixmap 8x8 — exatamente o mesmo formato
        # usado no header "Sessões Claude" (`main_window._ensure_sessoes_bucket`).
        # Importante: o QPushButton anterior tinha 14x14 e empurrava o
        # ícone+label pra direita, desalinhando os dois grupos. Aqui
        # usamos QLabel + mousePressEvent — sem hover, sem fixed size
        # extra, alinhamento idêntico ao bucket Sessões.
        self._collapse_btn = QLabel()
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setPixmap(
            _ic("fa5s.chevron-down", color="#9aa0a6").pixmap(_QS(8, 8))
        )
        self._collapse_btn.setToolTip("Recolher / expandir runners")
        if on_toggle_collapse is not None:
            self._collapse_btn.mousePressEvent = (  # type: ignore[method-assign]
                lambda _ev, cb=on_toggle_collapse: cb()
            )
        row.addWidget(self._collapse_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Ícone SVG (mdi6.source-branch) à esquerda do label — simetria
        # com o bucket Sessões Claude que já tem ícone fa5s.comments.
        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(
            _ic("mdi6.source-branch", color="#9aa0a6").pixmap(_QS(12, 12))
        )
        row.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._label = QLabel(label)
        # Mesma cor/tamanho do header "Sessões Claude" pra paridade visual.
        self._label.setStyleSheet(
            "color: #c8c8c8; font-size: 11px; font-weight: 600;"
        )
        row.addWidget(self._label, 0, Qt.AlignmentFlag.AlignVCenter)

        # Badge de contagem total (escondido se 0/None) — mesmo visual do
        # bucket Sessões Claude na sidebar.
        self._count_badge = QLabel("")
        self._count_badge.setStyleSheet(
            "background: #2a2a2a; color: #9aa0a6; font-size: 9px; "
            "font-weight: 700; padding: 1px 6px; border-radius: 6px;"
        )
        self._count_badge.setVisible(False)
        row.addWidget(self._count_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        # Badge de runners em execução (verde) — fica do lado do total
        # quando há ao menos 1 runner rodando. Ajuda a ver de relance
        # quantos estão de fato online sem precisar abrir a lista.
        self._running_badge = QLabel("")
        self._running_badge.setStyleSheet(
            "background: rgba(90,195,90,0.18); color: #7ad97a; font-size: 9px; "
            "font-weight: 700; padding: 1px 6px; border-radius: 6px;"
        )
        self._running_badge.setToolTip("Runners em execução")
        self._running_badge.setVisible(False)
        row.addWidget(self._running_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        row.addStretch(1)

        if on_restart_all is not None:
            self._restart_all_btn = QPushButton("↻")
            self._restart_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._restart_all_btn.setFixedSize(20, 18)
            self._restart_all_btn.setToolTip("Reiniciar todos os runners deste escopo")
            self._restart_all_btn.setStyleSheet(_BTN_QSS)
            self._restart_all_btn.clicked.connect(on_restart_all)
            row.addWidget(self._restart_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        if on_stop_all is not None:
            self._stop_all_btn = QPushButton("■")
            self._stop_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._stop_all_btn.setFixedSize(20, 18)
            self._stop_all_btn.setToolTip("Parar todos os runners deste escopo")
            self._stop_all_btn.setStyleSheet(_BTN_QSS)
            self._stop_all_btn.clicked.connect(on_stop_all)
            row.addWidget(self._stop_all_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._add_btn = QPushButton("＋")
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setFixedSize(20, 18)
        self._add_btn.setToolTip("Novo runner neste escopo")
        self._add_btn.setStyleSheet(_BTN_QSS)
        self._on_add_blank = on_add_blank
        self._on_generate = on_generate
        self._add_btn.clicked.connect(self._open_add_menu)
        row.addWidget(self._add_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_count(self, count: int | None) -> None:
        """Mostra '[N]' à direita do label. None ou 0 esconde."""
        if not count:
            self._count_badge.setVisible(False)
            return
        self._count_badge.setText(str(count))
        self._count_badge.setVisible(True)

    def set_running_count(self, count: int | None) -> None:
        """Mostra badge verde com a contagem de runners em execução.
        None ou 0 esconde — assim em workspace ocioso só aparece o
        badge cinza do total."""
        if not count:
            self._running_badge.setVisible(False)
            return
        # `●` antes do número deixa o pulso "ligado" visual mesmo a
        # 9px, em paridade com os dots verdes das linhas de runner.
        self._running_badge.setText(f"● {count}")
        self._running_badge.setToolTip(f"{count} runner(s) em execução")
        self._running_badge.setVisible(True)

    def set_collapsed(self, collapsed: bool) -> None:
        """Atualiza o ícone do chevron (right recolhido, down expandido)."""
        from PySide6.QtCore import QSize as _QS
        from .icons import ic as _ic
        name = "fa5s.chevron-right" if collapsed else "fa5s.chevron-down"
        self._collapse_btn.setPixmap(
            _ic(name, color="#9aa0a6").pixmap(_QS(8, 8))
        )

    def _open_add_menu(self) -> None:
        # Se não tem gerador (escopo console-pending sem area), abre direto.
        if self._on_generate is None:
            self._on_add_blank()
            return
        menu = QMenu(self)
        a_blank = menu.addAction("Em branco")
        a_blank.triggered.connect(lambda: self._on_add_blank())
        a_gen = menu.addAction("Gerar com Claude")
        a_gen.triggered.connect(lambda: self._on_generate())
        menu.exec(self._add_btn.mapToGlobal(self._add_btn.rect().bottomLeft()))
