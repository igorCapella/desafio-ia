import re

from app.dados.conexao import py_normalizar

AVISO = "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA PROFERIDA"  # a faixa que a interface exibe
_MARCA = "proposta de texto gerada por ia"  # parte do aviso usada na detecção (tolera pontuação)
_VERBOS = (r"elabore|elaborar|elabora|redija|redigir|redige|minute|minutar|proponha|propor|"
           r"fa[çc]a|fazer|escreva|escrever|prepare|preparar|gere|gerar|crie|criar")
# Pedido de minuta: a palavra "minuta", ou um verbo de redação com a SENTENÇA como objeto direto
# ("redija a sentença", "escreva uma nova sentença") — não "faça um resumo da sentença" (spec §6).
_RX_PEDIDO = re.compile(
    rf"\bminutas?\b|\b(?:{_VERBOS})\s+"
    r"(?:(?:uma|um|a|o|nova|novo|outra|proposta\s+de|modelo\s+de|projeto\s+de|rascunho\s+de)\s+){0,3}"
    r"senten[çc]a\b", re.I)
_RX_DISPOSITIVO = re.compile(r"\bjulgo\s+(parcialmente\s+)?(procedente|improcedente)", re.I)
_RX_CITADO = re.compile(r"\[[^\]]*\]|[“\"][^”\"\n]*[”\"]")  # colchetes e trechos entre aspas
_RX_SECAO = re.compile(r"^\s*(?:#+\s*|\*\*\s*)?(?:[IVX]+\s*[-–.]\s*)?"
                       r"(relat[óo]rio|fundamenta[çc][ãa]o|dispositivo)\b", re.I | re.M)
_RX_AVISO_JULGADO = re.compile(r"j[áa]\s+(?:foi\s+)?(?:julgad|sentenciad)|"
                               r"j[áa]\s+(?:existe|h[áa])\s+senten[çc]a|"
                               r"senten[çc]a\s+j[áa]\s+(?:foi\s+)?proferida", re.I)


def _selo(status: str, mensagem: str, trechos: list[str] | None = None) -> dict:
    return {"tipo": "minuta", "status": status, "mensagem": mensagem, "trechos": trechos or []}


def eh_minuta(resposta: str, pergunta: str) -> bool:
    if _MARCA in (resposta or "").lower():
        return True
    return bool(_RX_PEDIDO.search(pergunta or ""))


def _redigiu(resposta: str) -> bool:
    # Minuta de fato redigida: ao menos duas das seções Relatório, Fundamentação e Dispositivo.
    return len({m.group(1).lower()[:5] for m in _RX_SECAO.finditer(resposta)}) >= 2


def _assinada_por(resposta: str, magistrado: str) -> bool:
    fim = [linha for linha in resposta.strip().splitlines() if linha.strip()][-5:]
    nome = py_normalizar(magistrado)
    return any(nome in py_normalizar(linha) for linha in fim)


def _avisou_sentenca(resposta: str, sentencas: list[int]) -> bool:
    return bool(_RX_AVISO_JULGADO.search(resposta)) or any(
        re.search(rf"\[Doc\.?\s*{i}\b", resposta) for i in sentencas)


def verificar_minuta(resposta: str, *, magistrado: str | None = None,
                     n_documentos: int | None = None, ja_julgado: bool = False,
                     sentencas: list[int] | None = None) -> list[dict]:
    selos = []
    # Decisão entre colchetes é lacuna para o magistrado; entre aspas é citação da sentença que já existe.
    if _RX_DISPOSITIVO.search(_RX_CITADO.sub(" ", resposta)):
        selos.append(_selo("alerta", "A minuta propõe uma decisão de mérito fora de colchetes; "
                                     "decidir cabe ao magistrado."))
    else:
        selos.append(_selo("ok", "Dispositivo deixado à decisão do magistrado."))
    redigiu = _redigiu(resposta)
    if redigiu and _MARCA not in resposta.lower():
        selos.append(_selo("alerta", "Minuta sem o aviso de proposta (a interface insere a faixa)."))
    if magistrado and _assinada_por(resposta, magistrado):
        selos.append(_selo("alerta", "A minuta traz o nome do magistrado na assinatura; a IA não "
                                     "assina por ele.", [magistrado]))
    if n_documentos == 0 and redigiu:
        selos.append(_selo("alerta", "Minuta redigida para processo sem documentos: não há "
                                     "elementos dos autos para fundamentá-la."))
    if ja_julgado and redigiu and not _avisou_sentenca(resposta, sentencas or []):
        selos.append(_selo("alerta", "O processo já tem sentença e a minuta não avisa isso."))
    return selos
