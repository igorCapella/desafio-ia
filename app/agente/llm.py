import asyncio
import json
from typing import AsyncIterator

import httpx

from app.config import get_settings

_QUANT = ["fp8", "mxfp8", "bf16", "fp16", "fp32"]
_TENTATIVAS = 3           # spec §5.2: novas tentativas com espera crescente em 429 e 5xx
_ESPERA_BASE_S = 1.0
_esperar = asyncio.sleep  # substituível nos testes


def custo_de(uso: dict) -> float:
    try:
        return float(uso.get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def montar_corpo(mensagens: list[dict], tools: list[dict]) -> dict:
    s = get_settings()
    corpo = {
        "models": [s.llm_model, s.llm_model_reserva],
        "messages": mensagens,
        "stream": True,
        "usage": {"include": True},
        "provider": {"quantizations": _QUANT, "require_parameters": True,
                     "data_collection": "deny", "allow_fallbacks": True},
        "reasoning": {"effort": s.reasoning_effort},
    }
    if tools:
        corpo["tools"] = tools
    return corpo


def cliente_http() -> httpx.AsyncClient:
    s = get_settings()
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0") if s.force_ipv4 else None
    return httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0), transport=transport)


def juntar_reasoning(fragmentos: list[dict]) -> list[dict]:
    """No streaming, cada bloco de raciocínio chega em pedaços com o mesmo tipo e índice;
    junta os pedaços para devolver ao modelo o bloco como ele foi gerado."""
    juntos: list[dict] = []
    for f in fragmentos:
        ult = juntos[-1] if juntos else None
        if ult is not None and (ult.get("type"), ult.get("index")) == (f.get("type"), f.get("index")):
            for k, v in f.items():
                if k in ("text", "summary", "data"):
                    ult[k] = (ult.get(k) or "") + (v or "")
                elif v is not None:
                    ult[k] = v
        else:
            juntos.append(dict(f))
    return juntos


def novo_acumulador() -> dict:
    return {"tools": {}, "reasoning": [], "concluiu": False, "terminou": False}


def parse_linha_sse(linha: str, acc: dict) -> list[dict]:
    """Converte uma linha SSE do OpenRouter em eventos normalizados. Função pura (sem rede)."""
    if not linha.startswith("data:"):
        return []  # comentários (": OPENROUTER PROCESSING") e linhas vazias
    dado = linha[5:].strip()
    if dado == "[DONE]":
        acc["terminou"] = True
        return []
    obj = json.loads(dado)
    if obj.get("error"):
        erro = obj["error"]
        msg = erro.get("message") if isinstance(erro, dict) else erro
        raise RuntimeError(f"Erro do provedor durante a resposta: {msg}")
    eventos: list[dict] = []
    if obj.get("usage"):
        # Modelo e provedor efetivos (com fallback podem variar) vão para o log de auditoria.
        eventos.append({"tipo": "uso", "uso": obj["usage"],
                        "modelo": obj.get("model"), "provedor": obj.get("provider")})
    for ch in obj.get("choices") or []:
        delta = ch.get("delta") or {}
        if delta.get("content"):
            eventos.append({"tipo": "texto", "delta": delta["content"]})
        if delta.get("reasoning_details"):
            acc["reasoning"].extend(delta["reasoning_details"])
        for tc in delta.get("tool_calls") or []:
            i = tc.get("index", 0)
            slot = acc["tools"].setdefault(i, {"id": tc.get("id"), "type": "function",
                                               "function": {"name": "", "arguments": ""}})
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] = fn["name"]
            if fn.get("arguments"):
                slot["function"]["arguments"] += fn["arguments"]
            if tc.get("id"):
                slot["id"] = tc["id"]
        if ch.get("finish_reason") and not acc["concluiu"]:
            # O OpenRouter repete o finish_reason no pedaço final (o do uso): só o primeiro vale.
            acc["concluiu"] = True
            if acc["reasoning"]:
                eventos.append({"tipo": "reasoning",
                                "reasoning_details": juntar_reasoning(acc["reasoning"])})
            if acc["tools"]:
                eventos.append({"tipo": "tool_calls",
                                "tool_calls": [acc["tools"][k] for k in sorted(acc["tools"])]})
            eventos.append({"tipo": "fim", "finish": ch["finish_reason"]})
    return eventos


def _repetir(status: int) -> bool:
    return status == 429 or status >= 500


async def stream_completion(mensagens: list[dict], tools: list[dict]) -> AsyncIterator[dict]:
    """Eventos normalizados da resposta. Consuma o gerador até o fim: o evento 'uso'
    pode chegar depois do 'fim'."""
    s = get_settings()
    corpo = montar_corpo(mensagens, tools)
    headers = {"Authorization": f"Bearer {s.openrouter_api_key}",
               "Content-Type": "application/json"}
    for tentativa in range(_TENTATIVAS):
        ultima = tentativa == _TENTATIVAS - 1
        acc = novo_acumulador()
        emitiu = False
        try:
            async with cliente_http() as cli:
                async with cli.stream("POST", f"{s.llm_base_url}/chat/completions",
                                      headers=headers, json=corpo) as resp:
                    if resp.status_code != 200:
                        erro = (await resp.aread()).decode(errors="replace")[:500]
                        if _repetir(resp.status_code) and not ultima:
                            await _esperar(_ESPERA_BASE_S * 2 ** tentativa)
                            continue
                        raise RuntimeError(f"HTTP {resp.status_code}: {erro}")
                    async for linha in resp.aiter_lines():
                        for ev in parse_linha_sse(linha, acc):
                            emitiu = True
                            yield ev
                        if acc["terminou"]:
                            break
                    if not acc["concluiu"]:
                        raise RuntimeError("A resposta do provedor terminou sem conclusão.")
                    return
        except httpx.TransportError:
            # Falha de conexão antes de qualquer evento: repetir não duplica texto na tela.
            if emitiu or ultima:
                raise
            await _esperar(_ESPERA_BASE_S * 2 ** tentativa)
