import sqlite3
from collections.abc import AsyncIterable
from contextlib import aclosing, asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agente.ciclo import responder
from app.agente.sessao import nova_sessao, obter_sessao
from app.auditoria import custo_acumulado, registrar
from app.config import get_settings
from app.dados.conexao import abrir_conexao, abrir_conexao_consulta
from app.verificacao.citacoes import FERRAMENTAS_DE_CONSULTA
from app.verificacao.minuta import AVISO, eh_minuta
from app.verificacao.selos import verificar

AUDITORIA = "logs/auditoria.jsonl"
_TABELAS = {"processo", "parte", "processo_parte", "documento", "movimentacao",
            "magistrado", "unidade"}
_EM_ANDAMENTO: set[str] = set()  # conversas com uma pergunta em curso


def _validar_banco(caminho: str) -> None:
    # Spec §4.1: o arquivo existe e tem as 7 tabelas esperadas; senão, falha com mensagem clara.
    if not Path(caminho).is_file():
        raise RuntimeError(f"Banco não encontrado em {caminho}. Confira DB_PATH no .env.")
    try:
        with closing(sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)) as c:
            tabelas = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    except sqlite3.DatabaseError as e:
        raise RuntimeError(f"{caminho} não é um banco SQLite válido ({e}).") from None
    faltando = _TABELAS - tabelas
    if faltando:
        raise RuntimeError(f"Banco inválido em {caminho}: faltam as tabelas "
                           f"{', '.join(sorted(faltando))}.")


@asynccontextmanager
async def _ciclo_de_vida(_app: FastAPI):
    _validar_banco(get_settings().db_path)
    # As visões e a base de consulta do modelo sobem já no arranque: um SQLite sem memdb falha
    # aqui, com mensagem clara, e não no meio da primeira conversa.
    with closing(abrir_conexao_consulta()):
        pass
    yield


app = FastAPI(title="Agente de Consulta Processual", lifespan=_ciclo_de_vida)


class Pergunta(BaseModel):
    sessao_id: str = Field(max_length=64)
    pergunta: str = Field(min_length=1, max_length=4000)


def _sse(evento: str, dados: dict) -> ServerSentEvent:
    return ServerSentEvent(event=evento, data=dados)  # o FastAPI serializa `data` em JSON


@app.get("/api/saude")
def saude():
    s = get_settings()
    return {"ok": True, "modelo": s.llm_model, "modelo_reserva": s.llm_model_reserva,
            "reasoning_effort": s.reasoning_effort, "mascarar_cpf": s.mascarar_cpf,
            "custo_acumulado": round(custo_acumulado(AUDITORIA), 4), "orcamento": s.orcamento_usd}


@app.post("/api/sessao/nova")
def sessao_nova():
    return {"sessao_id": nova_sessao()}


@app.get("/api/documento/{doc_id}")
def documento(doc_id: int, sessao_id: str = Query(max_length=64)):
    # Só documentos lidos nesta conversa (spec §7): o painel não vira porta para varrer o banco por id.
    sessao = obter_sessao(sessao_id)
    negado = HTTPException(status_code=403, detail="Documento fora do escopo desta conversa.")
    if doc_id not in sessao.docs_vistos:
        raise negado
    with closing(abrir_conexao()) as conn:
        row = conn.execute("select id, numero, tipo, autor, data_juntada, paginas, texto "
                           "from v_documentos where id=?", (doc_id,)).fetchone()
    if row is None:
        raise negado
    return dict(row)


def _registrar_recusa(p: Pergunta, motivo: str) -> None:
    # Spec §9.3: um registro por pergunta — inclusive as recusadas antes de chegar ao modelo.
    registrar({"sessao": p.sessao_id, "pergunta": p.pergunta, "recusada": motivo, "custo": 0.0},
              caminho=AUDITORIA)


# O próprio endpoint é o gerador de eventos: é assim que o FastAPI 0.141 faz SSE nativo
# (response_class=EventSourceResponse; ele cuida do formato, do keepalive e da desconexão).
@app.post("/api/chat", response_class=EventSourceResponse)
async def chat(p: Pergunta) -> AsyncIterable[ServerSentEvent]:
    s = get_settings()
    sessao = obter_sessao(p.sessao_id)
    if custo_acumulado(AUDITORIA) >= s.orcamento_usd:  # no teto ou acima (spec §5.5)
        _registrar_recusa(p, "orcamento")
        yield _sse("erro", {"mensagem": "Orçamento do protótipo atingido; novas perguntas "
                                        "estão suspensas."})
        return
    if p.sessao_id in _EM_ANDAMENTO:
        _registrar_recusa(p, "em_andamento")
        yield _sse("erro", {"mensagem": "Já há uma pergunta em andamento nesta conversa; "
                                        "aguarde a resposta."})
        return
    _EM_ANDAMENTO.add(p.sessao_id)
    custo_antes = sessao.custo_total
    resposta, uso, ferramentas, erros, selos = "", {}, [], [], []
    houve_sql, gravado, minuta = False, False, False

    def gravar(interrompida: bool) -> None:
        # Um registro por pergunta (spec §9.3), inclusive quando o cliente desconecta no meio.
        nonlocal gravado
        gravado = True
        registrar({"sessao": p.sessao_id, "pergunta": p.pergunta, "resposta": resposta, "eh_minuta": minuta,
                   "processo_em_foco": sessao.processo_em_foco, "ferramentas": ferramentas,
                   "modelo": uso.get("modelo"), "provedor": uso.get("provedor"),
                   "tokens": {k: uso.get(k, 0) for k in ("prompt", "completion", "raciocinio")},
                   "custo": round(sessao.custo_total - custo_antes, 6),
                   "latencia_ms": uso.get("latencia_ms"), "selos": selos, "erros": erros,
                   "interrompida": interrompida}, caminho=AUDITORIA)
    try:
        async with aclosing(responder(sessao, p.pergunta)) as eventos:
            async for ev in eventos:
                tipo = ev["tipo"]
                if tipo == "texto":
                    resposta += ev["delta"]
                    yield _sse("texto", {"delta": ev["delta"]})
                elif tipo == "ferramenta":
                    houve_sql = houve_sql or ev["nome"] in FERRAMENTAS_DE_CONSULTA
                    ferramentas.append({k: ev.get(k) for k in ("nome", "args", "duracao_ms", "resumo")})
                    yield _sse("ferramenta", {k: v for k, v in ev.items() if k != "tipo"})
                elif tipo == "status":
                    yield _sse("status", {k: v for k, v in ev.items() if k != "tipo"})
                elif tipo == "processo":
                    yield _sse("processo", ev["ficha"])
                elif tipo == "erro":
                    erros.append({"mensagem": ev["mensagem"], "detalhe": ev.get("detalhe")})
                    yield _sse("erro", {"mensagem": ev["mensagem"]})
                elif tipo == "fim":
                    uso = ev["uso"]
        yield _sse("status", {"fase": "verificando"})
        try:
            ver = verificar(resposta, p.pergunta, sessao, houve_sql=houve_sql,
                            mascarar_cpf=s.mascarar_cpf)
        except Exception as e:
            ver = {"selos": [{"tipo": "sistema", "status": "alerta",
                              "mensagem": "Verificação indisponível neste turno.", "trechos": []}],
                   "eh_minuta": eh_minuta(resposta, p.pergunta, sessao.ultimo_turno_minuta)}
            erros.append({"mensagem": "Falha na verificação.",
                          "detalhe": f"{type(e).__name__}: {e}"[:300]})
        selos, minuta = ver["selos"], ver["eh_minuta"]
        gravar(interrompida=False)  # antes do fim: a resposta só termina depois de registrada
        custo_sessao = round(sessao.custo_total, 4)  # lido antes de liberar a conversa
        _EM_ANDAMENTO.discard(p.sessao_id)  # e a conversa já aceita a próxima pergunta
        yield _sse("verificacao", {**ver, "aviso": AVISO if ver["eh_minuta"] else None})
        yield _sse("fim", {"uso": uso, "custo_sessao": custo_sessao})
    finally:
        _EM_ANDAMENTO.discard(p.sessao_id)
        if not gravado:
            gravar(interrompida=True)


# Por último: rotas /api/* registradas acima têm prioridade sobre os arquivos estáticos.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web" / "static", html=True,
                           check_dir=False), name="web")
