#!/usr/bin/env python3
"""SPIKE DESCARTÁVEL — consolida spike_out/*.json num relatório Markdown."""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "spike_out"
aliases = sys.argv[1].split(",") if len(sys.argv) > 1 else sorted(p.stem for p in OUT.glob("*.json") if not p.stem.startswith("historico"))
res = [json.loads((OUT / f"{a}.json").read_text()) for a in aliases if (OUT / f"{a}.json").exists()]

# Recalcula as checagens com a versão atual das regras (mantém "citações existem", que depende do histórico).
sys.path.insert(0, str(OUT.parent))
from spike_modelos import CHECKS  # noqa: E402
for r in res:
    for c in r["casos"]:
        if c["finish"] != "erro":
            c["checks"] = CHECKS[c["caso"]](c["resposta"], c["ferramentas"]) + [
                (k, v) for k, v in c["checks"] if k == "citações existem"]
casos = [c["caso"] for c in res[0]["casos"]] if res else []

linhas = ["| Modelo | " + " | ".join(casos) + " | Chamadas | Tokens entrada/saída (raciocínio) | Latência | Custo US$ |",
          "|---|" + "---|" * len(casos) + "---|---|---|---|"]
for r in res:
    cel, calls, tin, tout, treas, lat, cost = [], 0, 0, 0, 0, 0.0, 0.0
    for c in r["casos"]:
        base = [(k, v) for k, v in c["checks"] if not k.startswith("BÔNUS")]
        bonus = [v for k, v in c["checks"] if k.startswith("BÔNUS")]
        ok = sum(v for _, v in base)
        s = "✅" if ok == len(base) else f"❌ {ok}/{len(base)}"
        if bonus and all(bonus):
            s += "★"
        if c["finish"] == "erro":
            s = "💥"
        cel.append(s)
        u = c["uso"]
        calls += u.get("llm_calls", 0); tin += u.get("prompt", 0); tout += u.get("completion", 0)
        treas += u.get("reasoning", 0); lat += u.get("latencia", 0); cost += u.get("cost", 0)
    linhas.append(f"| {r['alias']} | " + " | ".join(cel) + f" | {calls} | {tin:,}/{tout:,} ({treas:,}) | {lat:.0f}s | {cost:.4f} |")
print("\n".join(linhas))
print("\n✅ passou em todas as checagens · ❌ n/m checagens · ★ bônus · 💥 erro\n")

for r in res:
    for c in r["casos"]:
        falhas = [k for k, v in c["checks"] if not v]
        if falhas or c["finish"] != "stop":
            print(f"- {r['alias']} {c['caso']}: falhou em {falhas} (finish={c['finish']})")

if "--respostas" in sys.argv:
    for r in res:
        for c in r["casos"]:
            print(f"\n\n======== {r['alias']} · {c['caso']} · {c['pergunta']}")
            for f in c["ferramentas"]:
                print(f"  ⚙ {f['ferramenta']}({json.dumps(f['args'], ensure_ascii=False)[:160]}) → {f['resultado'][:160]}")
            print(f"  uso: {c['uso']}")
            print(c["resposta"])
