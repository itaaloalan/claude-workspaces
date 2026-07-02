"""_PerfApplication: dispatch de input lento vira [INPUT-PERF] no log.

Roda num SUBPROCESS porque a suíte já tem um QApplication de sessão (o
notify override precisa ser da instância única do processo). O script filho
clica num botão cujo handler dorme 150ms e imprime o log capturado.
"""
from __future__ import annotations

import os
import subprocess
import sys

_SCRIPT = """
import logging, io, time, sys
from pathlib import Path
buf = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(buf))
logging.getLogger().setLevel(logging.INFO)
from claude_workspaces import perf
perf.init(True, Path(sys.argv[1]))
from claude_workspaces.app import _PerfApplication
from PySide6.QtWidgets import QPushButton
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
app = _PerfApplication([])
btn = QPushButton("lento")
btn.setObjectName("BotaoTeste")
btn.clicked.connect(lambda: time.sleep(0.15))
btn.show()
QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
app.processEvents()
print(buf.getvalue())
"""


def test_slow_input_dispatch_logged(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(tmp_path / "perf.log")],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "[INPUT-PERF] dispatch lento: MouseButtonRelease" in proc.stdout
    assert "QPushButton#BotaoTeste" in proc.stdout
