"""Resumo do log de auditoria (spec §9.3): uv run python scripts/resumo_logs.py [caminho]."""
import json
import sys
from collections import Counter
from pathlib import Path


def _registros(caminho: str) -> list[dict]:
    p = Path(caminho)
    if not p.exists():
        return []
    registros = []
    for linha in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linha)
        except ValueError:
            continue  # linha corrompida (gravação interrompida)
        if isinstance(r, dict):
            registros.append(r)
    return registros


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(len(ordenados) * p))]


def resumir(caminho: str = "logs/auditoria.jsonl") -> dict:
    regs = _registros(caminho)
    respondidas = [r for r in regs if not r.get("recusada")]
    latencias = [r["latencia_ms"] for r in respondidas
                 if isinstance(r.get("latencia_ms"), (int, float))]
    return {
        "perguntas": len(regs),
        "recusadas": sum(1 for r in regs if r.get("recusada")),
        "interrompidas": sum(1 for r in respondidas if r.get("interrompida")),
        "com_erro": sum(1 for r in respondidas if r.get("erros")),
        "custo_total": round(sum(float(r.get("custo") or 0) for r in regs), 6),
        "latencia_p50_ms": _percentil(latencias, 0.5),
        "latencia_p95_ms": _percentil(latencias, 0.95),
        "contagem_selos": dict(Counter(f"{s['tipo']}:{s['status']}"
                                       for r in regs for s in r.get("selos") or [])),
        "modelos": dict(Counter(r["modelo"] for r in respondidas if r.get("modelo"))),
        "provedores": dict(Counter(r["provedor"] for r in respondidas if r.get("provedor"))),
    }


if __name__ == "__main__":
    print(json.dumps(resumir(*sys.argv[1:2]), ensure_ascii=False, indent=2))
