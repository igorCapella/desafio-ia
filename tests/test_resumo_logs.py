import json

from scripts.resumo_logs import resumir


def _escrever(p, registros, extra=""):
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in registros) + "\n" + extra,
                 encoding="utf-8")


def test_resumo(tmp_path):
    p = tmp_path / "aud.jsonl"
    _escrever(p, [
        {"custo": 0.002, "latencia_ms": 10, "modelo": "m", "provedor": "A",
         "selos": [{"tipo": "citacao", "status": "ok"}]},
        {"custo": 0.003, "latencia_ms": 20, "modelo": "m", "provedor": "B", "interrompida": True,
         "selos": [{"tipo": "norma", "status": "alerta"}], "erros": [{"mensagem": "x"}]},
        {"custo": 0.0, "recusada": "orcamento"},
    ], extra='{"custo": 0.0\n')  # última linha corrompida
    r = resumir(str(p))
    assert abs(r["custo_total"] - 0.005) < 1e-9
    assert (r["perguntas"], r["recusadas"], r["interrompidas"], r["com_erro"]) == (3, 1, 1, 1)
    assert (r["latencia_p50_ms"], r["latencia_p95_ms"]) == (20, 20)
    assert r["contagem_selos"] == {"citacao:ok": 1, "norma:alerta": 1}
    assert r["provedores"] == {"A": 1, "B": 1}


def test_resumo_sem_log(tmp_path):
    assert resumir(str(tmp_path / "nao-existe.jsonl"))["perguntas"] == 0
