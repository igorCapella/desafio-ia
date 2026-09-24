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
    return f"{nome}({', '.join(f'{k}={v!r}' for k, v in args.items())})"


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

    def _encerrar() -> dict:
        uso_total["latencia_ms"] = round((time.monotonic() - inicio_turno) * 1000, 1)
        sessao.custo_total += uso_total["cost"]
        return {"tipo": "fim", "uso": uso_total}

    for _passo in range(MAX_PASSOS):
        yield {"tipo": "status", "fase": "pensando"}
        texto_buf, tool_calls, reasoning = "", None, None
        try:
            async for ev in stream_fn(
                    [{k: v for k, v in m.items() if not k.startswith("_")} for m in sessao.historico],
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
            sessao.custo_total += uso_total["cost"]
            yield {"tipo": "erro", "mensagem": f"Falha ao consultar o modelo: {e}"}
            return

        msg = {"role": "assistant", "content": texto_buf}
        if reasoning:
            msg["reasoning_details"] = reasoning
        if tool_calls:
            msg["tool_calls"] = tool_calls
        sessao.adicionar(msg)

        if not tool_calls:
            yield _encerrar()
            return

        yield {"tipo": "status", "fase": "consultando"}
        for tc in tool_calls:
            nome = tc["function"]["name"]
            args: dict = {}
            inicio = time.monotonic()
            try:
                args = _argumentos(nome, tc["function"].get("arguments"))
                res = await _executar(sessao, nome, args)
            except ArgumentoInvalido as e:
                res = {"erro": str(e)}
            except Exception as e:
                res = {"erro": f"Falha interna ao executar a ferramenta ({type(e).__name__})."}
            duracao_ms = round((time.monotonic() - inicio) * 1000, 1)
            sessao.registrar_resultado(nome, res)
            numero = None
            if nome == "obter_dossie" and res.get("encontrado"):
                p = res["processo"]
                numero = p["numero"]
                sessao.definir_foco(numero, {"classe": p["classe"], "situacao": p["situacao"]})
                sessao.compactar_dossies_antigos(ate=limite_compactacao)
                yield {"tipo": "processo", "ficha": _ficha(res)}
            consultas.append(_descrever(nome, args))
            yield {"tipo": "ferramenta", "nome": nome, "args": args, "duracao_ms": duracao_ms,
                   "resumo": _resumo_resultado(nome, res)}
            msg_tool = {"role": "tool", "tool_call_id": tc.get("id"), "name": nome,
                        "content": json.dumps(res, ensure_ascii=False)}
            if numero:
                msg_tool["_numero"] = numero
            sessao.adicionar(msg_tool)

    aviso = (f"Não consegui concluir a resposta dentro do limite de {MAX_PASSOS} passos. "
             f"Consultas feitas: {'; '.join(consultas)}.")
    sessao.adicionar({"role": "assistant", "content": aviso})
    yield {"tipo": "texto", "delta": aviso}
    yield _encerrar()
