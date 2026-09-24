import json

import httpx
import pytest

from app.agente import llm
from app.agente.llm import (custo_de, juntar_reasoning, montar_corpo, novo_acumulador,
                            parse_linha_sse)


def _sse(*objs) -> str:
    return "".join(f"data: {json.dumps(o)}\n\n" for o in objs) + "data: [DONE]\n\n"


def test_custo_com_e_sem_campo():
    assert custo_de({"cost": 0.0021}) == 0.0021
    assert custo_de({}) == 0.0  # provedor omitiu 'cost' — Review Focus
    assert custo_de({"prompt_tokens": 10}) == 0.0


def test_corpo_tem_roteamento_e_reasoning():
    corpo = montar_corpo([{"role": "user", "content": "oi"}], tools=[])
    assert corpo["provider"]["data_collection"] == "deny"
    assert "fp8" in corpo["provider"]["quantizations"]
    assert corpo["provider"]["require_parameters"] is True
    assert corpo["reasoning"]["effort"] == "high"
    assert corpo["stream"] is True
    assert corpo["models"][0] == "deepseek/deepseek-v4.1-flash"


def test_parse_ignora_comentarios_e_detecta_fim():
    acc = novo_acumulador()
    assert parse_linha_sse(": OPENROUTER PROCESSING", acc) == []
    assert parse_linha_sse("", acc) == []
    assert parse_linha_sse("data: [DONE]", acc) == []
    assert acc["terminou"] is True


def test_parse_acumula_tool_call_em_pedacos():
    acc = novo_acumulador()
    objs = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {
            "name": "obter_dossie", "arguments": '{"nu'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
            "arguments": 'mero": "1"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    eventos = [e for o in objs for e in parse_linha_sse("data: " + json.dumps(o), acc)]
    tc = next(e for e in eventos if e["tipo"] == "tool_calls")["tool_calls"]
    assert tc == [{"id": "c1", "type": "function",
                   "function": {"name": "obter_dossie", "arguments": '{"numero": "1"}'}}]
    assert eventos[-1] == {"tipo": "fim", "finish": "tool_calls"}


def test_juntar_reasoning_reune_pedacos_do_mesmo_bloco():
    pedacos = [{"type": "reasoning.text", "index": 0, "text": "Pri", "format": "x"},
               {"type": "reasoning.text", "index": 0, "text": "meiro"},
               {"type": "reasoning.text", "index": 1, "text": "Outro"}]
    assert juntar_reasoning(pedacos) == [
        {"type": "reasoning.text", "index": 0, "text": "Primeiro", "format": "x"},
        {"type": "reasoning.text", "index": 1, "text": "Outro"}]


def test_parse_erro_no_meio_do_stream():
    with pytest.raises(RuntimeError, match="sobrecarga"):
        parse_linha_sse('data: {"error": {"message": "sobrecarga"}}', novo_acumulador())


def _instalar_transporte(monkeypatch, respostas):
    """Cada chamada ao provedor consome a próxima resposta falsa (status, corpo)."""
    chamadas = []

    def handler(request):
        chamadas.append(json.loads(request.content))
        status, corpo = respostas[len(chamadas) - 1]
        return httpx.Response(status, content=corpo.encode(),
                              headers={"content-type": "text/event-stream"})

    async def sem_espera(_segundos):
        return None

    monkeypatch.setattr(llm, "cliente_http",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(llm, "_esperar", sem_espera)
    return chamadas


async def _coletar(gen):
    return [e async for e in gen]


@pytest.mark.anyio
async def test_stream_completo_texto_reasoning_uso(monkeypatch):
    corpo = _sse(
        {"choices": [{"delta": {"reasoning_details": [
            {"type": "reasoning.text", "index": 0, "text": "pen"}]}}]},
        {"choices": [{"delta": {"reasoning_details": [
            {"type": "reasoning.text", "index": 0, "text": "so"}]}}]},
        {"choices": [{"delta": {"content": "Olá"}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001}},
    )
    _instalar_transporte(monkeypatch, [(200, ": OPENROUTER PROCESSING\n\n" + corpo)])
    eventos = await _coletar(llm.stream_completion([{"role": "user", "content": "oi"}], []))
    assert [e["tipo"] for e in eventos] == ["texto", "reasoning", "fim", "uso"]
    assert eventos[1]["reasoning_details"] == [
        {"type": "reasoning.text", "index": 0, "text": "penso"}]
    assert custo_de(eventos[3]["uso"]) == 0.0001


@pytest.mark.anyio
async def test_stream_repete_em_429_e_depois_responde(monkeypatch):
    ok = _sse({"choices": [{"delta": {"content": "oi"}, "finish_reason": "stop"}]})
    chamadas = _instalar_transporte(monkeypatch, [(429, "limite"), (200, ok)])
    eventos = await _coletar(llm.stream_completion([{"role": "user", "content": "oi"}], []))
    assert len(chamadas) == 2
    assert eventos[0] == {"tipo": "texto", "delta": "oi"}


@pytest.mark.anyio
async def test_stream_nao_repete_erro_do_cliente(monkeypatch):
    chamadas = _instalar_transporte(monkeypatch, [(400, "requisição inválida")])
    with pytest.raises(RuntimeError, match="HTTP 400"):
        await _coletar(llm.stream_completion([{"role": "user", "content": "oi"}], []))
    assert len(chamadas) == 1


@pytest.mark.anyio
async def test_stream_sem_conclusao_vira_erro(monkeypatch):
    _instalar_transporte(monkeypatch, [(200, 'data: {"choices": [{"delta": {"content": "o"}}]}\n\n')])
    with pytest.raises(RuntimeError, match="sem conclusão"):
        await _coletar(llm.stream_completion([{"role": "user", "content": "oi"}], []))


@pytest.fixture
def anyio_backend():
    return "asyncio"
