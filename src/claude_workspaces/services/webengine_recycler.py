"""WebEngineRecycler — watchdog de memória do renderer dos terminais.

Todos os consoles/runners carregam o mesmo terminal.html (mesma origem
file://) e, com `--process-per-site` (app.py), vivem num ÚNICO processo
QtWebEngineProcess renderer. Esse processo nunca reinicia enquanto existir
ao menos uma view viva — e a view ativa fica viva por dias — então o heap
do Blink acumula sem teto (já chegou a 8GB entre RSS e swap, empurrando a
máquina inteira pra swap thrash).

Recuperar essa memória exige matar o PROCESSO: `view.reload()` ou
`setLifecycleState(Discarded)` recriam a page no mesmo renderer, e o
PartitionAlloc não devolve as arenas acumuladas ao SO. O ciclo aqui:

1. `on_sample()` recebe os `RendererStat` (RSS+swap por renderer) do
   `ResourceSampler` a cada ~8s. Renderer acima do limiar por 2 amostras
   consecutivas — e que seja realmente o dos terminais, confirmado por
   `page().renderProcessPid()` das views vivas — dispara o recycle.
2. `recycle_now()` descarrega TODAS as views de terminal (page count do
   site → 0 → o Chromium encerra o renderer sozinho), polla a morte do
   pid e, se não morrer em 6s, SIGKILL (seguro: nossas pages já foram
   destruídas).
3. Com o processo morto, recarrega a view ativa de cada área visível —
   o replay buffer existente reconstrói o xterm em ~0,1-1s.

Enquanto `recycling_active()` for True, `ensure_view_loaded`/`_build_view`
e a `_MaterializeQueue` seguram a criação de views: uma page criada nessa
janela nasceria no renderer moribundo e o manteria vivo.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, QTimer

from ..process_monitor import RendererStat, human_bytes

log = logging.getLogger(__name__)

# Flag de módulo (não de instância): os guards em terminal_widget/
# runner_widget/terminal_area consultam sem precisar de referência ao
# recycler — e só existe um ciclo por vez no app inteiro.
_recycling = False


def recycling_active() -> bool:
    return _recycling


def _default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _default_kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        log.warning("SIGKILL falhou pro renderer pid=%d", pid, exc_info=True)


class WebEngineRecycler(QObject):
    # Telemetria [WEBENGINE-MEM] começa bem antes do limiar de recycle,
    # pra dar histórico de crescimento no app.log.
    LOG_THRESHOLD = 500 * 1024 * 1024
    # Throttle do log por pid — sem isso um renderer inchado geraria uma
    # linha a cada amostra de 8s (~10k linhas/dia).
    LOG_EVERY_S = 60
    OVER_SAMPLES = 2          # amostras consecutivas acima do limiar
    COOLDOWN_S = 600          # mínimo entre recycles
    DEATH_POLL_MS = 250
    DEATH_TIMEOUT_MS = 6000
    KILL_EXTRA_WAIT_MS = 2000

    def __init__(
        self,
        *,
        threshold_bytes: Callable[[], int],
        collect_loaded: Callable[[], list],
        reload_active: Callable[[], None],
        pid_alive: Callable[[int], bool] = _default_pid_alive,
        kill_pid: Callable[[int], None] = _default_kill_pid,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._threshold_bytes = threshold_bytes
        self._collect_loaded = collect_loaded
        self._reload_active = reload_active
        self._pid_alive = pid_alive
        self._kill_pid = kill_pid
        self._over_count = 0
        self._last_recycle = 0.0
        self._last_log: dict[int, float] = {}
        self._target_pids: list[int] = []
        self._recycle_started = 0.0
        self._before_bytes = 0
        self._killed = False
        self._death_timer = QTimer(self)
        self._death_timer.setInterval(self.DEATH_POLL_MS)
        self._death_timer.timeout.connect(self._poll_death)

    # ------------------------------------------------------------- sampling

    def on_sample(self, renderers: Iterable[RendererStat]) -> None:
        """Chamado na main thread a cada amostra do ResourceSampler."""
        renderers = list(renderers or [])
        now = time.monotonic()
        for r in renderers:
            total = r.rss + r.swap
            if total >= self.LOG_THRESHOLD and (
                now - self._last_log.get(r.pid, 0.0) >= self.LOG_EVERY_S
            ):
                self._last_log[r.pid] = now
                log.info(
                    "[WEBENGINE-MEM] renderer pid=%d rss=%s swap=%s total=%s",
                    r.pid, human_bytes(r.rss), human_bytes(r.swap),
                    human_bytes(total),
                )
        # Poda pids mortos do throttle de log.
        alive = {r.pid for r in renderers}
        self._last_log = {p: t for p, t in self._last_log.items() if p in alive}

        threshold = int(self._threshold_bytes() or 0)
        if threshold <= 0 or _recycling:
            self._over_count = 0
            return
        if now - self._last_recycle < self.COOLDOWN_S:
            return

        ours = self._terminal_renderer_pids()
        bloated = [
            r for r in renderers
            if r.rss + r.swap >= threshold and r.pid in ours
        ]
        if not bloated:
            self._over_count = 0
            return
        self._over_count += 1
        if self._over_count < self.OVER_SAMPLES:
            return
        self._over_count = 0
        worst = max(bloated, key=lambda r: r.rss + r.swap)
        self.recycle_now(
            f"rss+swap {human_bytes(worst.rss + worst.swap)} > limiar "
            f"{human_bytes(threshold)}",
            pids=[r.pid for r in bloated],
            before_bytes=worst.rss + worst.swap,
        )

    def _terminal_renderer_pids(self) -> set[int]:
        """Pids de renderer das NOSSAS views de terminal. Outras
        QWebEngineViews do app (diff, git panel, PWAs) têm renderers
        próprios sob --process-per-site — reciclar terminais por causa
        delas não liberaria nada."""
        pids: set[int] = set()
        for w in self._collect_loaded():
            view = getattr(w, "view", None)
            if view is None:
                continue
            try:
                pid = int(view.page().renderProcessPid())
            except (RuntimeError, AttributeError):
                continue
            if pid > 0:
                pids.add(pid)
        return pids

    # -------------------------------------------------------------- recycle

    def recycle_now(
        self,
        reason: str,
        *,
        pids: list[int] | None = None,
        before_bytes: int = 0,
    ) -> bool:
        global _recycling
        if _recycling:
            return False
        targets = list(pids) if pids else sorted(self._terminal_renderer_pids())
        widgets = self._collect_loaded()
        if not targets and not widgets:
            return False
        _recycling = True
        self._target_pids = targets
        self._recycle_started = time.monotonic()
        self._before_bytes = before_bytes
        self._killed = False
        log.warning(
            "[WEBENGINE-RECYCLE] início pids=%s views_descarregadas=%d motivo=%s",
            targets, len(widgets), reason,
        )
        for w in widgets:
            try:
                w.unload_view()
            except RuntimeError:
                pass  # widget Qt destruído entre o collect e o unload
        # Os deleteLater() precisam do event loop pra destruir as pages —
        # a espera pela morte do processo é assíncrona por construção.
        self._death_timer.start()
        return True

    def _poll_death(self) -> None:
        survivors = [p for p in self._target_pids if self._pid_alive(p)]
        if not survivors:
            self._finish()
            return
        elapsed_ms = (time.monotonic() - self._recycle_started) * 1000.0
        if not self._killed and elapsed_ms >= self.DEATH_TIMEOUT_MS:
            self._killed = True
            for p in survivors:
                log.warning("[WEBENGINE-RECYCLE] fallback SIGKILL pid=%d", p)
                self._kill_pid(p)
        elif self._killed and elapsed_ms >= (
            self.DEATH_TIMEOUT_MS + self.KILL_EXTRA_WAIT_MS
        ):
            # Nem o SIGKILL resolveu (zumbi aguardando reap do Chromium) —
            # segue em frente; as pages novas nascem em processo novo.
            self._finish()

    def _finish(self) -> None:
        global _recycling
        self._death_timer.stop()
        _recycling = False
        self._last_recycle = time.monotonic()
        dt = time.monotonic() - self._recycle_started
        try:
            self._reload_active()
        except Exception:
            log.exception("[WEBENGINE-RECYCLE] reload_active falhou")
        old = set(self._target_pids)
        self._target_pids = []
        log.warning(
            "[WEBENGINE-RECYCLE] concluído dt=%.1fs antes=%s (pid(s) novo(s) "
            "no próximo [WEBENGINE-MEM])",
            dt, human_bytes(self._before_bytes),
        )

        def _log_after() -> None:
            fresh = self._terminal_renderer_pids()
            if fresh & old:
                log.warning(
                    "[WEBENGINE-RECYCLE] pid %s sobreviveu ao recycle — "
                    "alguma page de terminal não foi destruída",
                    sorted(fresh & old),
                )

        QTimer.singleShot(10_000, _log_after)


__all__ = ["WebEngineRecycler", "recycling_active"]
