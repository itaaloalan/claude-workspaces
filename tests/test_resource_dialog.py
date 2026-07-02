"""ResourceDialog não pode morrer com grupos grandes.

Regressão do OverflowError: `QProgressBar.setMaximum` recebe int de 32 bits;
passar RSS em BYTES estourava com grupos >2 GiB e a exceção no `_render` do
`__init__` matava o diálogo antes do `show()` — o clique no footer parecia
não fazer nada. As barras agora trabalham em MB.
"""
from __future__ import annotations

from claude_workspaces.process_monitor import (
    CAT_APP,
    CAT_CONSOLE,
    FreeResult,
    ProcGroup,
    Snapshot,
)
from claude_workspaces.ui.resource_dialog import ResourceDialog

FIVE_GB = 5 * 1024 ** 3
ONE_GB = 1024 ** 3


def _snapshot() -> Snapshot:
    return Snapshot(
        total_rss=FIVE_GB + ONE_GB,
        total_cpu=42.0,
        n_procs=7,
        n_zombies=0,
        groups=[
            ProcGroup(key=("app",), category=CAT_APP, label="App", rss=FIVE_GB),
            ProcGroup(key=("c", 1), category=CAT_CONSOLE, label="Console x",
                      rss=ONE_GB, pid=1234),
        ],
    )


def _mk_dialog(qapp) -> ResourceDialog:
    return ResourceDialog(
        snapshot_provider=_snapshot,
        on_free=lambda: FreeResult(0, 0, 0, 0, 0),
        on_stop=lambda pid: None,
        on_kill=lambda pid: None,
    )


def test_render_survives_groups_above_2gib(qapp):
    dlg = _mk_dialog(qapp)  # __init__ chama _render — antes estourava aqui
    try:
        bar = dlg._rows_by_key[("app",)]["bar"]
        assert bar.maximum() == FIVE_GB // (1024 * 1024)
        assert bar.value() == bar.maximum()
        small = dlg._rows_by_key[("c", 1)]["bar"]
        assert small.value() == ONE_GB // (1024 * 1024)
    finally:
        dlg._timer.stop()
        dlg.deleteLater()


def test_dialog_shows_after_render(qapp):
    dlg = _mk_dialog(qapp)
    try:
        dlg.show()
        assert dlg.isVisible()
    finally:
        dlg._timer.stop()
        dlg.close()
        dlg.deleteLater()
