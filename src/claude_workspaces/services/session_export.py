"""Exporta uma sessão Claude (JSONL) como markdown legível.

Útil pra:
- Documentar decisões: cola o markdown numa PR description ou wiki
- Compartilhar: arquivo .md auto-contido sem precisar de viewer
- Fork de conversa: usuário pode editar o md e colar como prompt

Mantém só user + assistant (text content); descarta tool_use detalhado
(o que tornaria o output gigante). Tool calls aparecem como uma linha
resumida 'Used tool: <name>'.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _format_timestamp(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return raw


def _extract_text(content) -> str:
    """Extrai texto plano de um content que pode ser str ou list de blocos."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t == "text":
                parts.append(c.get("text") or "")
            elif t == "tool_use":
                name = c.get("name") or "?"
                inp = c.get("input") or {}
                # Resumo de uma linha
                summary = ""
                if isinstance(inp, dict):
                    skill = inp.get("skill")
                    if skill:
                        summary = f" · /{skill}"
                    elif "command" in inp:
                        cmd = str(inp.get("command", ""))[:80]
                        summary = f" · {cmd}"
                parts.append(f"_(used {name}{summary})_")
            elif t == "tool_result":
                # Resumo curto do output do tool
                tc = c.get("content")
                if isinstance(tc, str):
                    short = tc[:120].replace("\n", " ")
                    parts.append(f"_(tool result: {short}…)_" if len(tc) > 120 else f"_(tool result: {short})_")
        return "\n\n".join(p for p in parts if p)
    return ""


def export_to_markdown(jsonl_path: Path) -> str:
    """Lê o JSONL e devolve string markdown formatada."""
    lines_md: list[str] = []
    metadata: dict = {}
    try:
        fp = jsonl_path.open(encoding="utf-8")
    except OSError as e:
        return f"# Erro lendo sessão\n\n{e}"

    with fp:
        for line in fp:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not metadata:
                metadata = {
                    "session_id": msg.get("sessionId", jsonl_path.stem),
                    "cwd": msg.get("cwd", ""),
                    "branch": msg.get("gitBranch", ""),
                    "started": _format_timestamp(msg.get("timestamp", "")),
                }
            msg_type = msg.get("type")
            inner = msg.get("message")
            ts = _format_timestamp(msg.get("timestamp", ""))
            if msg_type == "user":
                if not isinstance(inner, dict):
                    continue
                text = _extract_text(inner.get("content"))
                if not text.strip():
                    continue
                lines_md.append(f"## 👤 User · {ts}\n\n{text}\n")
            elif msg_type == "assistant":
                if not isinstance(inner, dict):
                    continue
                text = _extract_text(inner.get("content"))
                model = inner.get("model", "")
                if not text.strip():
                    continue
                model_tag = f" `{model}`" if model else ""
                lines_md.append(f"## 🤖 Claude{model_tag} · {ts}\n\n{text}\n")

    header = "# Sessão Claude\n\n"
    if metadata:
        header += (
            f"- **ID:** `{metadata['session_id']}`\n"
            f"- **Pasta:** `{metadata['cwd']}`\n"
            f"- **Branch:** `{metadata['branch']}`\n"
            f"- **Iniciada em:** {metadata['started']}\n\n"
            "---\n\n"
        )
    return header + "\n".join(lines_md)
