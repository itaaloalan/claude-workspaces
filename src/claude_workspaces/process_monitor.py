"""Monitor de RAM/CPU do app e de tudo que ele forkou.

O claude-workspaces é um processo Qt que, além do próprio interpretador
Python + Chromium embutido (QtWebEngine), forka um processo por runner e
por console Claude (via `PtySession`, cada um session leader → pid == pgid).
Quando o usuário reclama que "o app está comendo RAM/CPU", o que importa é
a **árvore inteira** enraizada no PID do app, não só o processo principal.

`ProcessMonitor` caminha essa árvore (psutil), soma RSS e %CPU, e agrupa os
processos em linhas legíveis:
  • um grupo por runner/console (somando a subárvore daquele session leader);
  • um grupo "Navegador embutido" juntando os QtWebEngineProcess;
  • um grupo "App" pro processo principal e o resto.

`free_memory()` faz a faxina não-destrutiva: recolhe zumbis (processos
moribundos <defunct>), roda o GC do Python e devolve heap liberado ao SO via
`malloc_trim` — medindo o RSS do processo principal antes/depois.

Parar runners pesados NÃO é responsabilidade daqui: a UI faz isso pelo
caminho normal do widget (a `MainWindow` mapeia pid → runner/console), pra
que o estado da interface acompanhe.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import os
import re
from dataclasses import dataclass, field

import psutil

# Mascara user:senha em URLs (ex.: postgres dos MCP) pra não vazar no gerenciador.
_CRED_RE = re.compile(r"://[^/@\s:]+:[^/@\s]+@")

# Categorias de grupo, da mais "do usuário" pra mais "infra".
CAT_RUNNER = "runner"
CAT_CONSOLE = "console"
CAT_WEBENGINE = "webengine"
CAT_APP = "app"

# Só runners podem ser encerrados por aqui. Consoles aparecem (pra dar
# visibilidade do peso do Claude), mas matar um do gerenciador derrubaria
# uma sessão Claude em pleno trabalho — isso fica no fluxo normal da aba.
# Matar o app core ou o Chromium embutido derrubaria a janela inteira.
STOPPABLE = (CAT_RUNNER,)

_WEBENGINE_HINT = "qtwebengine"


@dataclass
class ProcInfo:
    """Um processo individual dentro de um grupo (linha expandida)."""

    pid: int
    name: str
    rss: int = 0
    cpu: float = 0.0
    cmdline: str = ""     # já mascarado (sem senha)
    zombie: bool = False


@dataclass
class ProcGroup:
    """Uma linha do gerenciador — um runner/console, o navegador ou o app."""

    key: tuple
    category: str
    label: str
    rss: int = 0          # bytes, somados na subárvore do grupo
    cpu: float = 0.0      # % (soma por processo, pode passar de 100 = >1 core)
    count: int = 0        # nº de processos dobrados nesta linha
    zombies: int = 0
    pid: int | None = None  # alvo de "encerrar" (session leader), se houver
    procs: list[ProcInfo] = field(default_factory=list)  # processos da subárvore

    @property
    def stoppable(self) -> bool:
        return self.category in STOPPABLE and self.pid is not None


def _short_cmdline(cmd: list[str], name: str) -> str:
    """Linha de comando curta e sem segredos pra exibir no gerenciador."""
    if not cmd:
        return name
    text = " ".join(cmd).strip()
    text = _CRED_RE.sub("://***@", text)
    # Encurta o primeiro token se for um caminho absoluto (mantém o basename).
    if text.startswith("/"):
        head, _, tail = text.partition(" ")
        text = (os.path.basename(head) + (" " + tail if tail else "")).strip()
    return text[:140]


@dataclass
class Snapshot:
    total_rss: int = 0
    total_cpu: float = 0.0
    n_procs: int = 0
    n_zombies: int = 0
    groups: list[ProcGroup] = field(default_factory=list)  # desc por RSS


@dataclass
class FreeResult:
    freed_rss: int        # bytes que o processo principal devolveu ao SO
    reaped_zombies: int
    before_rss: int
    after_rss: int
    gc_collected: int


def human_bytes(n: int) -> str:
    """Formata bytes em B/KB/MB/GB com 1 casa (estilo IDE)."""
    step = 1024.0
    val = float(max(0, n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < step or unit == "TB":
            if unit == "B":
                return f"{int(val)} B"
            return f"{val:.1f} {unit}"
        val /= step
    return f"{val:.1f} TB"


class ProcessMonitor:
    """Amostra a árvore de processos do app. Reentrante e tolerante a corridas.

    `root_pid` default = o próprio app (`os.getpid()`); injetável pra teste.
    Mantém objetos `psutil.Process` em cache entre amostras porque
    `cpu_percent()` é um delta desde a última chamada **no mesmo objeto** —
    recriar o objeto a cada tick zeraria o %CPU pra sempre.
    """

    def __init__(self, root_pid: int | None = None) -> None:
        self.root_pid = root_pid if root_pid is not None else os.getpid()
        self._cpu_cache: dict[int, psutil.Process] = {}
        # Prime do root pra que a 1ª amostra já tenha algum delta de CPU.
        try:
            p = psutil.Process(self.root_pid)
            p.cpu_percent(None)
            self._cpu_cache[self.root_pid] = p
        except psutil.Error:
            pass

    # ---- amostragem --------------------------------------------------------

    def _tree(self) -> list[psutil.Process]:
        try:
            root = psutil.Process(self.root_pid)
        except psutil.Error:
            return []
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except psutil.Error:
            pass
        return procs

    def _cpu(self, p: psutil.Process) -> float:
        """%CPU desde a amostra anterior, reusando o objeto em cache."""
        prev = self._cpu_cache.get(p.pid)
        if prev is not None:
            try:
                return float(prev.cpu_percent(None))
            except psutil.Error:
                pass
        # Primeiro encontro com este pid: registra e prima (retorna 0 agora).
        self._cpu_cache[p.pid] = p
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
        return 0.0

    def sample(self, leaders: dict[int, tuple[str, str]] | None = None) -> Snapshot:
        """Tira uma foto da árvore.

        `leaders`: pid de session leader → (categoria, rótulo). Qualquer
        processo cujo ancestral (ou ele mesmo) seja um desses pids é
        atribuído àquele grupo (a subárvore inteira do runner/console).
        """
        leaders = leaders or {}
        procs = self._tree()
        if not procs:
            return Snapshot()

        # ppid de cada processo da árvore — pra subir a cadeia até um leader.
        ppid: dict[int, int] = {}
        for p in procs:
            try:
                ppid[p.pid] = p.ppid()
            except psutil.Error:
                ppid[p.pid] = 0
        pidset = set(ppid)
        leader_pids = set(leaders)

        def owner(pid: int) -> int | None:
            cur = pid
            for _ in range(64):  # teto anti-ciclo
                if cur in leader_pids:
                    return cur
                nxt = ppid.get(cur)
                if nxt is None or nxt not in pidset:
                    return None
                cur = nxt
            return None

        groups: dict[tuple, ProcGroup] = {}
        total_rss = 0
        total_cpu = 0.0
        n_zombies = 0

        for p in procs:
            try:
                with p.oneshot():
                    rss = int(p.memory_info().rss)
                    name = p.name()
                    is_zombie = p.status() == psutil.STATUS_ZOMBIE
                    try:
                        cmd = p.cmdline()
                    except psutil.Error:
                        cmd = []
                cpu = self._cpu(p)
            except psutil.Error:
                continue

            total_rss += rss
            total_cpu += cpu
            if is_zombie:
                n_zombies += 1

            own = owner(p.pid)
            if own is not None:
                cat, label = leaders[own]
                key: tuple = ("leader", own)
                lead_pid: int | None = own
            elif _WEBENGINE_HINT in name.lower():
                key = ("webengine",)
                cat, label, lead_pid = CAT_WEBENGINE, "Navegador embutido (QtWebEngine)", None
            else:
                key = ("app",)
                cat, label, lead_pid = CAT_APP, "App (claude-workspaces)", None

            g = groups.get(key)
            if g is None:
                g = ProcGroup(key=key, category=cat, label=label, pid=lead_pid)
                groups[key] = g
            g.rss += rss
            g.cpu += cpu
            g.count += 1
            if is_zombie:
                g.zombies += 1
            g.procs.append(
                ProcInfo(
                    pid=p.pid,
                    name=name,
                    rss=rss,
                    cpu=cpu,
                    cmdline=_short_cmdline(cmd, name),
                    zombie=is_zombie,
                )
            )

        # Poda o cache de CPU pros pids que ainda existem (evita crescer sem fim).
        self._cpu_cache = {
            pid: proc for pid, proc in self._cpu_cache.items() if pid in pidset
        }

        for g in groups.values():
            g.procs.sort(key=lambda pi: pi.rss, reverse=True)
        ordered = sorted(groups.values(), key=lambda g: g.rss, reverse=True)
        return Snapshot(
            total_rss=total_rss,
            total_cpu=total_cpu,
            n_procs=len(pidset),
            n_zombies=n_zombies,
            groups=ordered,
        )

    # ---- faxina ------------------------------------------------------------

    def _root_rss(self) -> int:
        try:
            return int(psutil.Process(self.root_pid).memory_info().rss)
        except psutil.Error:
            return 0

    def _reap_zombies(self) -> int:
        """Recolhe filhos diretos <defunct>. Só dá pra reapear os PRÓPRIOS
        filhos (não netos), e só quando rodamos dentro do processo root."""
        if self.root_pid != os.getpid():
            return 0
        reaped = 0
        try:
            root = psutil.Process(self.root_pid)
            children = root.children(recursive=False)
        except psutil.Error:
            return 0
        for ch in children:
            try:
                if ch.status() != psutil.STATUS_ZOMBIE:
                    continue
            except psutil.Error:
                continue
            try:
                wpid, _ = os.waitpid(ch.pid, os.WNOHANG)
                if wpid:
                    reaped += 1
            except (ChildProcessError, OSError):
                pass
        return reaped

    @staticmethod
    def _malloc_trim() -> bool:
        """Devolve arenas livres do glibc ao SO. No-op fora do glibc/Linux."""
        try:
            name = ctypes.util.find_library("c") or "libc.so.6"
            libc = ctypes.CDLL(name, use_errno=True)
            if not hasattr(libc, "malloc_trim"):
                return False
            libc.malloc_trim(0)
            return True
        except (OSError, AttributeError):
            return False

    def free_memory(self) -> FreeResult:
        """Faxina não-destrutiva: zumbis + GC + malloc_trim. Não mexe em
        runners/consoles vivos — isso é decisão do usuário, feita na UI."""
        before = self._root_rss()
        reaped = self._reap_zombies()
        collected = gc.collect()
        self._malloc_trim()
        after = self._root_rss()
        return FreeResult(
            freed_rss=max(0, before - after),
            reaped_zombies=reaped,
            before_rss=before,
            after_rss=after,
            gc_collected=collected,
        )
