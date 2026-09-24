import re

from app.dados.conexao import py_normalizar

# [Doc 86], [Doc. 86 – Petição Inicial, 24/10/2022], [Doc 86, 90], [Docs 86 e 90], (Doc 86),
# [Doc 939, 2023-06-01; Doc 944, 2024-10-08]. Número seguido de "/" ou "-" é data, não documento.
_RX_MARCADOR_DOC = re.compile(r"[\[(]\s*Docs?(?![A-Za-zÀ-ÿ])[^\])]*[\])]", re.I)  # como no nucleo.js
_RX_IDS_DOC = re.compile(r"\bDocs?\.?\s*(\d+(?![\d/-])(?:\s*(?:,|;|\be\b)\s*\d+(?![\d/-]))*)", re.I)
_RX_MOV = re.compile(r"\[Mov\.?\s*([^\]]*)\]", re.I)
_RX_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})|(\d{4})-(\d{2})-(\d{2})")
_RX_PERIODO = re.compile(r"^\s*(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\s*(?:a|até|–|—|-)\s*"
                         r"(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\s*$", re.I)
_RX_SQL = re.compile(r"\[SQL", re.I)
# Ferramentas cujo resultado pode ser marcado [SQL] (consulta ao banco neste turno).
FERRAMENTAS_DE_CONSULTA = frozenset({"consultar_sql", "buscar_processos"})


def _norm(s: str) -> str:
    # minúsculas, sem acento, espaços colapsados, sem pontuação nas pontas
    return (py_normalizar(s) or "").strip(" .,;:-")


def _selo(status: str, mensagem: str, trechos: list[str] | None = None) -> dict:
    return {"tipo": "citacao", "status": status, "mensagem": mensagem, "trechos": trechos or []}


def _mov_confere(conteudo: str, movs_vistas: set[tuple[str, str]]) -> bool:
    # [Mov 30/09/2024 – Trânsito em Julgado] ou [Mov 2024-09-30 – ...]: a data (em qualquer dos
    # dois formatos) e a descrição, se houver, batem com uma movimentação lida na conversa.
    periodo = _RX_PERIODO.match(conteudo)
    if periodo:  # [Mov 11/10/2022 a 15/08/2024]: as duas pontas têm de ser movimentações lidas
        datas = {d for d, _ in movs_vistas}
        return all((p if "-" in p else "-".join(reversed(p.split("/")))) in datas
                   for p in (periodo[1], periodo[2]))
    m = _RX_DATA.search(conteudo)
    if not m:
        return False
    iso = f"{m[3]}-{m[2]}-{m[1]}" if m[1] else f"{m[4]}-{m[5]}-{m[6]}"
    descricao = _norm(conteudo[m.end():])
    return any(data == iso and (not descricao or _norm(d).startswith(descricao)
                                or descricao.startswith(_norm(d)))
               for data, d in movs_vistas)


def verificar_citacoes(resposta: str, docs_vistos: dict[int, str],
                       movs_vistas: set[tuple[str, str]], houve_sql: bool) -> list[dict]:
    selos: list[dict] = []
    docs_citados = {int(n) for marcador in _RX_MARCADOR_DOC.findall(resposta)
                    for grupo in _RX_IDS_DOC.findall(marcador) for n in re.findall(r"\d+", grupo)}
    invalidos = sorted(docs_citados - docs_vistos.keys())
    if docs_citados and not invalidos:
        selos.append(_selo("ok", f"{len(docs_citados)} citação(ões) de documento conferida(s)."))
    if invalidos:
        selos.append(_selo("alerta", "Citação de documento não consultado nesta conversa.",
                           [f"Doc {n}" for n in invalidos]))
    movs = [c.strip() for c in _RX_MOV.findall(resposta)]
    ruins = [f"Mov {c}" for c in movs if not _mov_confere(c, movs_vistas)]
    if movs and not ruins:
        selos.append(_selo("ok", f"{len(movs)} citação(ões) de movimentação conferida(s)."))
    if ruins:
        selos.append(_selo("alerta", "Citação de movimentação que não confere com as "
                                     "movimentações lidas nesta conversa.", ruins))
    if _RX_SQL.search(resposta):
        if houve_sql:
            selos.append(_selo("ok", "Dados marcados [SQL] vêm de consulta executada neste turno."))
        else:
            selos.append(_selo("alerta", "Marcou [SQL] sem ter executado consulta neste turno."))
    return selos
