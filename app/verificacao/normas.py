import re

_RX_SUMULA = re.compile(r"s[úu]mula\s+(?:vinculante\s+)?n?[º°.]?\s*(\d+)", re.I)
_RX_ART = re.compile(r"art(?:igo|\.)\s*(\d+)", re.I)
_JANELA_VERIFICAR = 80  # "[verificar]" vale até 80 caracteres depois da referência, na mesma linha


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def _marcada(resposta: str, fim: int) -> bool:
    return "[verificar]" in resposta[fim:fim + _JANELA_VERIFICAR].split("\n")[0].lower()


def verificar_normas(resposta: str, docs: dict[int, str]) -> list[dict]:
    corpus = _norm(" ".join(t or "" for t in docs.values()))
    externas = []
    for m in _RX_SUMULA.finditer(resposta):
        if _marcada(resposta, m.end()):
            continue
        if f"súmula {m.group(1)}" not in corpus and f"sumula {m.group(1)}" not in corpus:
            externas.append(f"Súmula {m.group(1)}")
    for m in _RX_ART.finditer(resposta):
        if _marcada(resposta, m.end()):
            continue
        if f"art. {m.group(1)}" not in corpus and f"artigo {m.group(1)}" not in corpus:
            externas.append(f"art. {m.group(1)}")
    if externas:
        return [{"tipo": "norma", "status": "alerta",
                 "mensagem": "Norma/súmula citada não encontrada nos autos; conferir.",
                 "trechos": sorted(set(externas))}]
    return [{"tipo": "norma", "status": "ok",
             "mensagem": "Referências normativas conferem com os autos ou estão ausentes.",
             "trechos": []}]
