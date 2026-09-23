#!/usr/bin/env python3
"""SPIKE DESCARTÁVEL — compara effort high vs max do V4.1 Flash nos casos difíceis."""
import json
import re
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent / "spike_out"
ALIASES = ["v4.1-high-r1", "v4.1-high-r2", "v4.1-max-r1", "v4.1-max-r2"]


def low(s):
    return (s or "").lower()


def contradicoes(texto):
    """Quais das 3 incoerências do processo 37 a resposta aponta."""
    t = low(texto)
    achou = set()
    if "saneamento" in t and re.search(r"contradi|incoer|inconsist|diverg|conflit|mudou|voltou atr[áa]s|havia (sido )?(expressamente )?afastad", t):
        achou.add("saneamento×sentença")
    if re.search(r"\b485\b|sem resolu[çc][ãa]o d[eo] m[ée]rito", t):
        achou.add("485×487")
    if re.search(r"(audi[êe]ncia|per[íi]cia|pericial).{0,250}(n[ãa]o (h[áa]|consta|constam|existe)|inexist|sem registro|aus[êe]ncia)", t, re.S) or \
       re.search(r"(n[ãa]o (h[áa]|consta|constam)|inexist).{0,250}(audi[êe]ncia|per[íi]cia|pericial)", t, re.S):
        achou.add("audiência/perícia inexistente")
    return achou


def decide_merito(minuta):
    sem_colchetes = re.sub(r"\[[^\]]*\]", " ", minuta)
    return bool(re.search(r"julgo\s+(parcialmente\s+)?(procedente|improcedente)", low(sem_colchetes)))


def sumulas_externas(minuta):
    return sorted({s for s in re.findall(r"s[úu]mula\s+(?:n[º°.]?\s*)?(\d+)", low(minuta)) if s != "385"})


def ressalva_d1(texto):
    t = low(texto)
    cita_unidade = "daiane" in t
    ressalva = bool(re.search(r"n[ãa]o [ée] poss[íi]vel afirmar|sem v[íi]nculo|n[ãa]o (h[áa]|existe) v[íi]nculo|n[ãa]o confirma|ressalva|"
                              r"n[ãa]o significa|n[ãa]o implica|coincid[êe]ncia|n[ãa]o (necessariamente|pode ser considerad)", t))
    return cita_unidade, ressalva


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _norm(s):
    s = re.sub(r"[*_`]", "", s).lower().replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def aspas(alias):
    total = ok = 0
    for conv in "ABD":
        f = OUT / f"historico_{alias}_{conv}.json"
        if not f.exists():
            continue
        corpus = []
        for m in json.loads(f.read_text()):
            if m["role"] == "tool":
                try:
                    corpus += list(_strings(json.loads(m["content"])))
                except Exception:
                    corpus.append(m["content"])
            elif m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
                c = _norm(" ".join(corpus))
                for q in re.findall(r'[“"]([^”"\n]{30,}?)[”"]', m["content"]):
                    if q[:1] in " ,.;:*" or "[doc" in q.lower():  # texto corrido entre aspas soltas, não citação
                        continue
                    frags = [_norm(x) for x in re.split(r"\.\.\.|…|\[\.\.\.\]|\(\.\.\.\)", q) if len(_norm(x)) >= 20]
                    if frags:
                        total += 1
                        ok += all(fr in c for fr in frags)
    return ok, total


linhas = ["| Config | Contradições (de 3) | Minuta decide o mérito? | Súmulas externas | D1: unidade / ressalva | Aspas literais | Raciocínio (tokens) | Latência total | Latência minuta | Custo US$ |",
          "|---|---|---|---|---|---|---|---|---|---|"]
for alias in ALIASES:
    f = OUT / f"{alias}.json"
    if not f.exists():
        linhas.append(f"| {alias} | (sem resultado) |")
        continue
    casos = {c["caso"]: c for c in json.loads(f.read_text())["casos"]}
    achou = contradicoes(casos.get("A1", {}).get("resposta", "")) | contradicoes(casos.get("A3", {}).get("resposta", ""))
    b1 = casos.get("B1", {}).get("resposta", "")
    un, res = ressalva_d1(casos.get("D1", {}).get("resposta", ""))
    ok, tot = aspas(alias)
    uso = [c["uso"] for c in casos.values()]
    provs = Counter(p for u in uso for p in u.get("provedores", []))
    linhas.append(
        f"| {alias} | {len(achou)} ({', '.join(sorted(achou)) or '—'}) | {'❌ sim' if decide_merito(b1) else '✅ não'} | "
        f"{', '.join(sumulas_externas(b1)) or '0'} | {'cita' if un else 'não cita'} / {'✅ com ressalva' if res else ('❌ sem ressalva' if un else '—')} | "
        f"{ok}/{tot} | {sum(u.get('reasoning', 0) for u in uso):,} | {sum(u.get('latencia', 0) for u in uso):.0f}s | "
        f"{casos.get('B1', {}).get('uso', {}).get('latencia', 0):.0f}s | {sum(u.get('cost', 0) for u in uso):.4f} |")
    print(f"{alias}: provedores={dict(provs)} | erros={[c['caso'] for c in casos.values() if c['finish'] != 'stop']}")
print()
print("\n".join(linhas))
