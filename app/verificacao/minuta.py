import re

from app.dados.conexao import py_normalizar
from app.verificacao.aspas import normalizar_trecho

AVISO = "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA PROFERIDA"  # a faixa que a interface exibe
_MARCA = "proposta de texto gerada por ia"  # parte do aviso usada na detecção (tolera pontuação)
_VERBOS = (r"elabore|elaborar|elabora|redija|redigir|redige|minute|minutar|proponha|propor|"
           r"fa[çc]a|fazer|escreva|escrever|prepare|preparar|gere|gerar|crie|criar")
# Pedido de minuta (spec §6): a palavra "minuta"; um verbo de redação com a SENTENÇA como objeto
# direto ("redija a sentença"); ou o substantivo ("proposta de sentença", "preciso de uma sentença").
# Não conta: "faça um resumo da sentença", "qual o dispositivo da sentença?".
_RX_PEDIDO = re.compile(
    r"\bminutas?\b"
    rf"|\b(?:{_VERBOS})\s+"
    r"(?:(?:uma|um|a|o|nova|novo|outra|proposta\s+de|modelo\s+de|projeto\s+de|rascunho\s+de)\s+){0,3}"
    r"senten[çc]a\b"
    r"|\b(?:proposta|projeto|modelo|rascunho|esbo[çc]o)\s+de\s+senten[çc]a\b"
    r"|\b(?:preciso|quero|gostaria)\s+(?:de\s+)?uma\s+(?:nova\s+)?senten[çc]a\b", re.I)
_RX_DISPOSITIVO = re.compile(r"\bjulgo\s+(parcialmente\s+)?(procedente|improcedente)", re.I)
_RX_ENTRE_ASPAS = re.compile(r'[“"]([^”"\n]+)[”"]')
_RX_SECAO = re.compile(r"^\s*(?:#+\s*|\*\*\s*)?(?:[IVX]+\s*[-–.]\s*)?"
                       r"(relat[óo]rio|fundamenta[çc][ãa]o|dispositivo)\b", re.I | re.M)
_RX_AVISO_JULGADO = re.compile(r"j[áa]\s+(?:foi\s+)?(?:julgad|sentenciad)|"
                               r"j[áa]\s+(?:existe|h[áa])\s+senten[çc]a|"
                               r"senten[çc]a\s+j[áa]\s+(?:foi\s+)?proferida", re.I)
_RX_CARGO = re.compile(r"\bju[ií]z(?:a|\(a\))?\b|magistrad", re.I)


def _selo(status: str, mensagem: str, trechos: list[str] | None = None) -> dict:
    return {"tipo": "minuta", "status": status, "mensagem": mensagem, "trechos": trechos or []}


def eh_minuta(resposta: str, pergunta: str) -> bool:
    if _MARCA in (resposta or "").lower():
        return True
    return bool(_RX_PEDIDO.search(pergunta or ""))


def _sem_lacunas_e_citacoes(resposta: str, docs: dict[int, str] | None) -> str:
    # Decisão entre colchetes é lacuna para o magistrado. Entre aspas, só sai da conferência o
    # trecho que está de fato nos autos (citação da sentença existente); aspas inventadas ficam.
    textos = [normalizar_trecho(t or "") for t in (docs or {}).values()]

    def _trocar(m: re.Match) -> str:
        trecho = normalizar_trecho(m.group(1))
        return " " if trecho and any(trecho in t for t in textos) else m.group(0)

    return _RX_ENTRE_ASPAS.sub(_trocar, re.sub(r"\[[^\]]*\]", " ", resposta))


def _redigiu(resposta: str) -> bool:
    # Minuta de fato redigida: ao menos duas das seções Relatório, Fundamentação e Dispositivo.
    return len({m.group(1).lower()[:5] for m in _RX_SECAO.finditer(resposta)}) >= 2


def _assinada_por(resposta: str, magistrado: str) -> bool:
    # Assinatura = o nome numa linha curta (sobra pouco além dele, como "Juiz de Direito") ou numa
    # linha breve vizinha do cargo — não uma menção ao magistrado no meio de uma frase.
    nome = py_normalizar(magistrado)
    linhas = [linha for linha in resposta.strip().splitlines() if linha.strip()][-12:]
    for i, linha in enumerate(linhas):
        norm = py_normalizar(linha) or ""
        if nome not in norm:
            continue
        resto = re.sub(r"[^a-z]", "", norm.replace(nome, ""))
        vizinhas = " ".join(linhas[max(0, i - 1):i + 2])
        if len(resto) <= 20 or (len(norm) <= len(nome) + 40 and _RX_CARGO.search(vizinhas)):
            return True
    return False


def _avisou_sentenca(resposta: str, sentencas: list[int]) -> bool:
    return bool(_RX_AVISO_JULGADO.search(resposta)) or any(
        re.search(rf"\[Doc\.?\s*{i}\b", resposta) for i in sentencas)


def verificar_minuta(resposta: str, *, magistrado: str | None = None,
                     n_documentos: int | None = None, ja_julgado: bool = False,
                     sentencas: list[int] | None = None,
                     docs: dict[int, str] | None = None) -> list[dict]:
    selos = []
    if _RX_DISPOSITIVO.search(_sem_lacunas_e_citacoes(resposta, docs)):
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
