"""FlowLayout — layout que dispõe os widgets em linha e quebra pra a
próxima quando não cabem na largura disponível (estilo "wrap"). Baseado
no exemplo clássico do Qt, com duas extensões:

- `align_right`: empacota cada linha encostada na borda direita (em vez
  da esquerda) — usado no header dos runners pra manter as ações coladas
  à direita mesmo depois de quebrar pra mais de uma linha.
- pula widgets escondidos (`isVisible() == False`) tanto no cálculo de
  altura quanto no posicionamento, pra botões opcionais (ex.: "Copiar do
  workspace", só em console) não deixarem buracos.

Implementa `hasHeightForWidth`/`heightForWidth` pra o layout-pai (vertical)
reservar a altura certa quando o conteúdo quebra em N linhas — sem isso o
header ficaria com altura de 1 linha e cortaria as demais.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy


class FlowLayout(QLayout):
    def __init__(
        self,
        parent=None,
        margin: int = 0,
        h_spacing: int = 6,
        v_spacing: int = 6,
        align_right: bool = False,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_space = h_spacing
        self._v_space = v_spacing
        self._align_right = align_right
        self.setContentsMargins(margin, margin, margin, margin)

    # --- API obrigatória do QLayout ------------------------------------
    def addItem(self, item: QLayoutItem) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # type: ignore[override]
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # type: ignore[override]
        size = QSize()
        for item in self._items:
            if item.widget() is not None and not item.widget().isVisible():
                continue
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    # --- Núcleo --------------------------------------------------------
    def _visible_items(self) -> list[QLayoutItem]:
        out = []
        for item in self._items:
            w = item.widget()
            if w is not None and not w.isVisible():
                continue
            out.append(item)
        return out

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        avail = eff.width()

        # 1) Agrupa os itens visíveis em linhas, respeitando a largura.
        rows: list[tuple[list[tuple[QLayoutItem, QSize]], int]] = []
        cur: list[tuple[QLayoutItem, QSize]] = []
        line_w = 0
        for item in self._visible_items():
            hint = item.sizeHint()
            if cur and line_w + self._h_space + hint.width() > avail:
                rows.append((cur, line_w))
                cur = []
                line_w = 0
            if cur:
                line_w += self._h_space
            line_w += hint.width()
            cur.append((item, hint))
        if cur:
            rows.append((cur, line_w))

        # 2) Posiciona cada linha (right-align opcional) e acumula altura.
        y = eff.y()
        for row_items, row_w in rows:
            row_h = max((h.height() for _, h in row_items), default=0)
            if self._align_right:
                x = eff.x() + max(0, avail - row_w)
            else:
                x = eff.x()
            for item, hint in row_items:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + self._h_space
            y += row_h + self._v_space

        if rows:
            y -= self._v_space  # remove o espaçamento extra da última linha
        return (y - eff.y()) + m.top() + m.bottom()
