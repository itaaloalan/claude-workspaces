"""Testes de plan_files.py — descoberta tail-first do plano (plan mode)
no transcript JSONL da sessão."""

import json

from claude_workspaces import plan_files
from claude_workspaces.plan_files import find_session_plan


def _write_plan(tmp_path, name="meu-plano.md", body="# Título do plano\n\ncorpo"):
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan = plans / name
    plan.write_text(body, encoding="utf-8")
    return plan


def _write_transcript(tmp_path, lines):
    t = tmp_path / "sessao.jsonl"
    t.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return t


def test_none_transcript():
    assert find_session_plan(None) is None


def test_transcript_inexistente(tmp_path):
    assert find_session_plan(tmp_path / "nao-existe.jsonl") is None


def test_sem_referencia_a_plano(tmp_path):
    t = _write_transcript(tmp_path, [{"type": "user", "message": "oi"}] * 5)
    assert find_session_plan(t) is None


def test_acha_plano_e_titulo(tmp_path):
    plan = _write_plan(tmp_path)
    t = _write_transcript(tmp_path, [
        {"type": "user", "message": "oi"},
        {"type": "assistant", "message": f"File created at: {plan}"},
    ])
    info = find_session_plan(t)
    assert info is not None
    assert info.path == plan
    assert info.title == "Título do plano"


def test_ultima_ocorrencia_vence(tmp_path):
    velho = _write_plan(tmp_path, "velho.md", "# Velho")
    novo = _write_plan(tmp_path, "novo.md", "# Novo")
    t = _write_transcript(tmp_path, [
        {"m": f"plano em {velho}"},
        {"m": "outra coisa"},
        {"m": f"plano em {novo}"},
    ])
    info = find_session_plan(t)
    assert info is not None
    assert info.path == novo


def test_plano_apagado_retorna_none(tmp_path):
    plan = _write_plan(tmp_path)
    t = _write_transcript(tmp_path, [{"m": f"plano em {plan}"}])
    plan.unlink()
    assert find_session_plan(t) is None


def test_titulo_fallback_slug(tmp_path):
    plan = _write_plan(tmp_path, "meu-plano-legal.md", "sem heading aqui")
    t = _write_transcript(tmp_path, [{"m": f"plano em {plan}"}])
    info = find_session_plan(t)
    assert info is not None
    assert info.title == "meu plano legal"


def test_cache_revalida_mtime_do_plano(tmp_path):
    plan = _write_plan(tmp_path, body="# V1")
    t = _write_transcript(tmp_path, [{"m": f"plano em {plan}"}])
    info1 = find_session_plan(t)
    assert info1 is not None and info1.title == "V1"
    # Reescreve o plano SEM mudar o transcript — cache deve revalidar
    # pelo mtime do .md e devolver o título novo.
    import os
    plan.write_text("# V2", encoding="utf-8")
    os.utime(plan, (plan.stat().st_atime, plan.stat().st_mtime + 10))
    info2 = find_session_plan(t)
    assert info2 is not None and info2.title == "V2"


def test_match_atravessa_fronteira_de_bloco(tmp_path, monkeypatch):
    """Path cortado na fronteira entre blocos do scan tail-first ainda
    é encontrado graças ao overlap."""
    monkeypatch.setattr(plan_files, "_CHUNK", 512)
    plan = _write_plan(tmp_path)
    filler = [{"m": "x" * 100} for _ in range(50)]
    t = _write_transcript(
        tmp_path,
        [{"m": f"plano em {plan}"}, *filler],
    )
    info = find_session_plan(t)
    assert info is not None
    assert info.path == plan
