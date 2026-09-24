import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator

from app.agente.llm import custo_de, stream_completion
from app.agente.sessao import Sessao
from app.dados.ferramentas import DEFINICOES_TOOLS, IMPL

_PROMPT = Path(__file__).with_name("prompt.md")
MAX_PASSOS = 8
MAX_CHAMADAS_POR_PASSO = 10
_PARAMETROS = {d["function"]["name"]: d["function"]["parameters"] for d in DEFINICOES_TOOLS}


class ArgumentoInvalido(ValueError):
    """Argumento de ferramenta recusado; a mensagem volta ao modelo, em português."""


def carregar_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


def _argumentos(nome: str, bruto: str | None) -> dict:
    # Só os parâmetros declarados em DEFINICOES_TOOLS, como texto: o modelo não consegue
    # passar mais nada às ferramentas (nem `conn`, nem `cpfs_do_usuario`).
    if nome not in _PARAMETROS:
        raise ArgumentoInvalido(f"Ferramenta desconhecida: {nome}.")
    try:
        args = json.loads(bruto or "{}")
    except json.JSONDecodeError:
        raise ArgumentoInvalido("Os argumentos da ferramenta não são um JSON válido.") from None
    if not isinstance(args, dict):
        raise ArgumentoInvalido("Os argumentos da ferramenta devem ser um objeto JSON.")
    declarados = _PARAMETROS[nome]["properties"]
    limpos = {}
    for k, v in args.items():
        if k not in declarados or v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (str, int, float)):
            raise ArgumentoInvalido(f"O parâmetro '{k}' deve ser texto.")
        limpos[k] = str(v)
    faltando = [k for k in _PARAMETROS[nome].get("required", []) if k not in limpos]
    if faltando:
        raise ArgumentoInvalido(f"Parâmetro obrigatório ausente: {', '.join(faltando)}.")
    return limpos


async def _executar(sessao: Sessao, nome: str, args: dict) -> dict:
    extra = {}
    if nome == "buscar_processos":
        extra["cpfs_do_usuario"] = frozenset(sessao.cpfs_do_usuario)
    # Em thread: uma consulta lenta (até 5 s) não trava as outras conversas (spec §4.2).
    return await asyncio.to_thread(IMPL[nome], **args, **extra)


async def _rodar_ferramenta(sessao: Sessao, tc: dict, indice: int) -> tuple[str, dict, dict, float]:
    nome = tc["function"]["name"]
    args: dict = {}
    inicio = time.monotonic()
    try:
        if indice >= MAX_CHAMADAS_POR_PASSO:
            raise ArgumentoInvalido(
                f"Limite de {MAX_CHAMADAS_POR_PASSO} chamadas de ferramenta por passo.")
        args = _argumentos(nome, tc["function"].get("arguments"))
        res = await _executar(sessao, nome, args)
    except ArgumentoInvalido as e:
        res = {"erro": str(e)}
    except Exception as e:
        res = {"erro": f"Falha interna ao executar a ferramenta ({type(e).__name__})."}
    return nome, args, res, round((time.monotonic() - inicio) * 1000, 1)


def _resumo_resultado(nome: str, res: dict) -> str:
    if res.get("erro"):
        return f"erro: {res['erro']}"
    if nome == "consultar_sql":
        return f"{len(res.get('linhas', []))} linha(s)"
    if nome == "buscar_processos":
        return f"{res.get('total', 0)} encontrado(s)"
    return f"{len(res.get('documentos', []))} docs, {len(res.get('alertas', []))} alerta(s)"


def _ficha(res: dict) -> dict:
    # Aba "Processo" da interface (spec §7); sem o texto integral dos documentos.
    return {**res["processo"], "partes": res["partes"], "advogados": res["advogados"],
            "ministerio_publico": res["ministerio_publico"], "alertas": res["alertas"],
            "movimentacoes": res["movimentacoes"],
            "documentos": [{k: d[k] for k in ("id", "tipo", "autor", "data_juntada", "paginas")}
                           for d in res["documentos"]]}


def _descrever(nome: str, args: dict) -> str:
    return f"{nome} ({'; '.join(f'{k}: {v}' for k, v in args.items())})" if args else nome


def _guardar_parcial(sessao: Sessao, texto: str) -> None:
    # Fecha o turno interrompido com uma resposta do assistente, para que a próxima
    # pergunta encontre um histórico válido (sem duas perguntas seguidas).
    ultima = sessao.historico[-1] if sessao.historico else {}
    if ultima.get("role") == "assistant" and not ultima.get("tool_calls"):
        return
    sessao.adicionar({"role": "assistant", "content": texto or "(resposta interrompida)"})


async def responder(sessao: Sessao, pergunta: str, *,
                    stream_fn=stream_completion) -> AsyncIterator[dict]:
    inicio_turno = time.monotonic()
    if not sessao.historico:
        sessao.adicionar({"role": "system", "content": carregar_prompt()})
    sessao.registrar_pergunta(pergunta)
    sessao.adicionar({"role": "user",
                      "content": f"{sessao.linha_de_contexto()}\n\nPergunta: {pergunta}"})
    limite_compactacao = len(sessao.historico)  # dossiês deste turno não são compactados
    uso_total = {"prompt": 0, "completion": 0, "raciocinio": 0, "cost": 0.0,
                 "modelo": None, "provedor": None, "latencia_ms": 0.0}
    consultas: list[str] = []
    texto_buf = ""
    encerrado = False

    def _encerrar() -> dict:
        nonlocal encerrado
        encerrado = True
        uso_total["latencia_ms"] = round((time.monotonic() - inicio_turno) * 1000, 1)
        sessao.custo_total += uso_total["cost"]
        return {"tipo": "fim", "uso": uso_total}

    try:
        for passo in range(MAX_PASSOS):
            yield {"tipo": "status", "fase": "pensando"}
            texto_buf, tool_calls, reasoning = "", None, None
            try:
                async for ev in stream_fn(
                        [{k: v for k, v in m.items() if not k.startswith("_")}
                         for m in sessao.historico],
                        DEFINICOES_TOOLS):
                    if ev["tipo"] == "texto":
                        if not texto_buf:
                            yield {"tipo": "status", "fase": "escrevendo"}
                        texto_buf += ev["delta"]
                        yield {"tipo": "texto", "delta": ev["delta"]}
                    elif ev["tipo"] == "tool_calls":
                        tool_calls = ev["tool_calls"]
                    elif ev["tipo"] == "reasoning":
                        reasoning = ev["reasoning_details"]
                    elif ev["tipo"] == "uso":
                        u = ev["uso"]
                        uso_total["cost"] += custo_de(u)
                        uso_total["prompt"] += u.get("prompt_tokens") or 0
                        uso_total["completion"] += u.get("completion_tokens") or 0
                        uso_total["raciocinio"] += (u.get("completion_tokens_details") or {}).get(
                            "reasoning_tokens") or 0
                        uso_total["modelo"] = ev.get("modelo") or uso_total["modelo"]
                        uso_total["provedor"] = ev.get("provedor") or uso_total["provedor"]
            except Exception as e:  # falha de rede/provedor
                encerrado = True
                sessao.custo_total += uso_total["cost"]
                _guardar_parcial(sessao, texto_buf)
                yield {"tipo": "erro",
                       "mensagem": "Não foi possível obter a resposta do modelo agora. Tente de novo.",
                       "detalhe": str(e)[:300]}
                return

            msg = {"role": "assistant", "content": texto_buf}
            if reasoning:
                msg["reasoning_details"] = reasoning
            if not tool_calls:
                sessao.adicionar(msg)
                yield _encerrar()
                return

            for i, tc in enumerate(tool_calls):
                tc["id"] = tc.get("id") or f"chamada_{passo}_{i}"  # o par pedido/resposta precisa de id
            msg["tool_calls"] = tool_calls
            resultados = []
            for i, tc in enumerate(tool_calls):
                yield {"tipo": "status", "fase": "consultando", "ferramenta": tc["function"]["name"]}
                resultados.append(await _rodar_ferramenta(sessao, tc, i))

            # O pedido de ferramentas e todas as respostas entram juntos no histórico: se a
            # conexão cair no meio do passo, não sobra pedido sem resposta.
            sessao.adicionar(msg)
            eventos = []
            for tc, (nome, args, res, duracao_ms) in zip(tool_calls, resultados):
                sessao.registrar_resultado(nome, res)
                msg_tool = {"role": "tool", "tool_call_id": tc["id"], "name": nome,
                            "content": json.dumps(res, ensure_ascii=False)}
                if nome == "obter_dossie" and res.get("encontrado"):
                    p = res["processo"]
                    msg_tool["_numero"] = p["numero"]
                    if p["numero"] != sessao.processo_em_foco:
                        eventos.append({"tipo": "processo", "ficha": _ficha(res)})
                    sessao.definir_foco(p["numero"], {"classe": p["classe"],
                                                      "situacao": p["situacao"]})
                    sessao.compactar_dossies_antigos(ate=limite_compactacao)
                sessao.adicionar(msg_tool)
                consultas.append(_descrever(nome, args))
                eventos.append({"tipo": "ferramenta", "nome": nome, "args": args,
                                "duracao_ms": duracao_ms, "resumo": _resumo_resultado(nome, res)})
            texto_buf = ""
            for ev in eventos:
                yield ev

        aviso = (f"Não consegui concluir a resposta dentro do limite de {MAX_PASSOS} passos. "
                 f"Consultas feitas: {'; '.join(consultas)}.")
        sessao.adicionar({"role": "assistant", "content": aviso})
        yield {"tipo": "texto", "delta": aviso}
        yield _encerrar()
    finally:
        if not encerrado:
            # Conexão encerrada no meio do turno: o histórico fica válido para a próxima
            # pergunta e o custo já gasto é contabilizado.
            sessao.custo_total += uso_total["cost"]
            _guardar_parcial(sessao, texto_buf)
