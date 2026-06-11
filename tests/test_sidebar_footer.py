"""Testes do SidebarFooter — lógica pura dos subcomponentes internos."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QCheckBox, QPushButton

from claude_workspaces.ui.sidebar_footer import (
    SidebarFooter,
    _ClickableLabel,
    _RunnerFooterRow,
    _UsageLabel,
)

# ---------- _UsageLabel ----------

@pytest.fixture
def usage_label(qapp):
    chip = QPushButton("—")
    label = _UsageLabel(chip)
    return label, chip


def test_usage_label_cooldown_pattern(usage_label):
    label, chip = usage_label
    label.setText("Você tem cooldown 5m restante")
    assert chip.text() == "cooldown 5m"


def test_usage_label_cooldown_hours(usage_label):
    label, chip = usage_label
    label.setText("Rate limit: cooldown 2h")
    assert chip.text() == "cooldown 2h"


def test_usage_label_hours_pct(usage_label):
    label, chip = usage_label
    label.setText("Uso: 4h 23%")
    assert chip.text() == "4h 23%"


def test_usage_label_pct_only(usage_label):
    label, chip = usage_label
    label.setText("87% do limite semanal")
    assert chip.text() == "87%"


def test_usage_label_html_stripped_before_match(usage_label):
    label, chip = usage_label
    # Rich text — o match deve acontecer no texto sem tags
    label.setText("<b>87%</b> do limite")
    assert chip.text() == "87%"


def test_usage_label_no_match_chip_unchanged(usage_label):
    label, chip = usage_label
    chip.setText("original")
    label.setText("sem padrão aqui")
    assert chip.text() == "original"


def test_usage_label_cooldown_takes_precedence_over_pct(usage_label):
    label, chip = usage_label
    label.setText("cooldown 3m — 50% do limite")
    # cooldown tem prioridade (return antecipado)
    assert chip.text() == "cooldown 3m"


def test_usage_label_hours_pct_takes_precedence_over_pct(usage_label):
    label, chip = usage_label
    label.setText("4h 70% usado")
    assert chip.text() == "4h 70%"


def test_usage_label_setText_updates_text(usage_label):
    label, chip = usage_label
    label.setText("Texto qualquer")
    assert label.text() == "Texto qualquer"


# ---------- _ClickableLabel ----------

def test_clickable_label_emits_clicked(qapp):
    label = _ClickableLabel()
    label.setText("v1.2.3")
    emitted = []
    label.clicked.connect(lambda: emitted.append(1))

    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        label.rect().center().toPointF(),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mousePressEvent(ev)
    assert emitted == [1]


def test_clickable_label_right_click_not_emitted(qapp):
    label = _ClickableLabel()
    emitted = []
    label.clicked.connect(lambda: emitted.append(1))

    ev = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress,
        label.rect().center().toPointF(),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    label.mousePressEvent(ev)
    assert emitted == []


# ---------- checkbox "criar no console" (include_in_stack) ----------

def _rows(footer: SidebarFooter):
    return footer.findChildren(_RunnerFooterRow)


def test_workspace_runner_has_stack_checkbox_reflecting_state(qapp):
    footer = SidebarFooter()
    footer.set_console_runners(
        [
            ("ws", "r1", "api", "idle", "parado", "", "/x/api", "workspace", True),
            ("ws", "r2", "web", "idle", "parado", "", "/x/web", "workspace", False),
        ],
        console_active=False,
    )
    rows = {r._runner_id: r for r in _rows(footer)}
    chk1 = rows["r1"].findChild(QCheckBox)
    chk2 = rows["r2"].findChild(QCheckBox)
    assert chk1 is not None and chk1.isChecked() is True
    assert chk2 is not None and chk2.isChecked() is False


def test_console_runner_has_no_stack_checkbox(qapp):
    footer = SidebarFooter()
    footer.set_console_runners(
        [
            ("ws", "rc", "api", "idle", "parado", "", "/x/api", "console", True),
        ],
        console_active=True,
    )
    rows = {r._runner_id: r for r in _rows(footer)}
    assert rows["rc"].findChild(QCheckBox) is None


def test_toggling_stack_checkbox_emits_signal(qapp):
    footer = SidebarFooter()
    got = []
    footer.runner_stack_toggle_requested.connect(
        lambda wid, rid, on: got.append((wid, rid, on))
    )
    footer.set_console_runners(
        [
            ("ws", "r1", "api", "idle", "parado", "", "/x/api", "workspace", True),
        ],
        console_active=False,
    )
    row = _rows(footer)[0]
    row.findChild(QCheckBox).setChecked(False)
    assert got == [("ws", "r1", False)]
