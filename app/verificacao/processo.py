import re

RX_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


def verificar_processo_foco(resposta: str, processo_em_foco: str | None,
                            conhecidos: set[str]) -> list[dict]:
    citados = set(RX_CNJ.findall(resposta))
    if not citados:
        return []
    estranhos = sorted(citados - conhecidos - {processo_em_foco})
    if estranhos:
        return [{"tipo": "processo", "status": "alerta",
                 "mensagem": "A resposta menciona processo não consultado nesta conversa.",
                 "trechos": estranhos}]
    return [{"tipo": "processo", "status": "ok",
             "mensagem": "Números de processo conferem com os consultados.", "trechos": []}]
