import re

_PREFIXO_SUMULA = r"s[úu]mulas?\s+(?:vinculantes?\s+)?(?:n[º°.]?\s*)?"
_PREFIXO_ART = r"\b(?:arts?\.|artigos?)\s*"
_NUM = r"\d{1,3}(?:\.\d{3})+|\d+"  # "1.699" é um número só (milhar), não o art. 1
_LISTA = rf"((?:{_NUM})(?:\s*(?:,|\be\b)\s*(?:{_NUM}))*)"  # "485", "485 e 487", "1.694, 1.699"
_RX_SUMULA = re.compile(_PREFIXO_SUMULA + _LISTA, re.I)
_RX_ART = re.compile(_PREFIXO_ART + _LISTA, re.I)
_JANELA_VERIFICAR = 80  # "[verificar]" vale até 80 caracteres antes ou depois, na mesma linha
_RX_MARCA = re.compile(r"\[verificar\b", re.I)  # também "[verificar — não citado nos autos]"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def _marcada(resposta: str, ini: int, fim: int) -> bool:
    antes = resposta[max(0, ini - _JANELA_VERIFICAR):ini].split("\n")[-1]
    depois = resposta[fim:fim + _JANELA_VERIFICAR].split("\n")[0]
    return _RX_MARCA.search(antes + depois) is not None


def _nos_autos(corpus: str, prefixo: str, n: str) -> bool:
    # O número aparece numa referência do mesmo tipo nos autos — inclusive dentro de uma lista
    # ("arts. 485 e 487") — e não como prefixo de outro número ("art. 5" não casa "art. 52").
    # Com ou sem ponto de milhar: "art. 1694" e "art. 1.694" são o mesmo artigo.
    digitos = r"\.?".join(re.findall(r"\d{1,3}(?=(?:\d{3})*$)", n))
    lista = rf"(?:(?:{_NUM})\s*(?:,|\be\b)\s*)*"
    return re.search(rf"{prefixo}{lista}{digitos}(?!\d|\.\d)", corpus) is not None


def verificar_normas(resposta: str, docs: dict[int, str],
                     textos_ferramentas: list[str] = ()) -> list[dict]:
    # Autos = documentos lidos e o que as ferramentas mostraram (movimentações, cadastro, buscas, SQL):
    # "Arquivamento Provisório (art. 40 LEF)" é descrição de movimentação, não de documento.
    corpus = _norm(" ".join([*(t or "" for t in docs.values()), *textos_ferramentas]))
    externas = []
    for rx, prefixo, rotulo in ((_RX_SUMULA, _PREFIXO_SUMULA, "Súmula"),
                                (_RX_ART, _PREFIXO_ART, "art.")):
        for m in rx.finditer(resposta):
            if _marcada(resposta, m.start(), m.end()):
                continue
            for n in re.findall(_NUM, m.group(1)):
                if not _nos_autos(corpus, prefixo, n.replace(".", "")):
                    externas.append(f"{rotulo} {n}")
    if externas:
        return [{"tipo": "norma", "status": "alerta",
                 "mensagem": "Norma/súmula citada não encontrada nos autos; conferir.",
                 "trechos": sorted(set(externas))}]
    return [{"tipo": "norma", "status": "ok",
             "mensagem": "Referências normativas conferem com os autos ou estão ausentes.",
             "trechos": []}]
