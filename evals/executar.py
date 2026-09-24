"""Avaliações com o modelo real (spec §9.2): uv run python -m evals [--sem-juiz] [--casos C01,C06]."""
import argparse
import asyncio
import json
import re
import time
from datetime import datetime
from pathlib import Path

import yaml

from app.agente.ciclo import responder
from app.agente.llm import custo_de, stream_completion
from app.agente.sessao import Sessao
from app.config import get_settings
from app.dados.conexao import py_normalizar
from app.verificacao.citacoes import FERRAMENTAS_DE_CONSULTA
from app.verificacao.selos import verificar

RAIZ = Path(__file__).parent
CASOS = RAIZ / "casos.yaml"
RUBRICA = RAIZ / "rubrica.md"
RESULTADOS = RAIZ / "resultados"
_MAX_DADOS_JUIZ = 40_000  # caracteres das ferramentas que o juiz recebe
_MAX_POR_FERRAMENTA = 20_000


def carregar_casos(caminho: Path = CASOS) -> list[dict]:
    return yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))["casos"]


def _contem(texto: str, alternativas: str) -> bool:
    # "a | b" = basta uma das alternativas; comparação sem acento e sem caixa.
    alvo = py_normalizar(texto) or ""
    return any((py_normalizar(a.strip()) or "") in alvo for a in alternativas.split("|"))


def checagens_objetivas(caso: dict, resposta: str, ferramentas: list[str],
                        selos: list[dict]) -> dict:
    e = caso["espera"]
    alertas = {s["tipo"] for s in selos if s["status"] == "alerta"}
    oks = {s["tipo"] for s in selos if s["status"] == "ok"}
    r = {
        "fatos_ok": all(_contem(resposta, f) for f in e.get("fatos", [])),
        "nao_deve_ok": not any(_contem(resposta, f) for f in e.get("nao_deve", [])),
        "ferramentas_ok": all(any(a.strip() in ferramentas for a in f.split("|"))
                              for f in e.get("ferramentas", [])),
        "selos_ok": set(e.get("selos_ok", [])) <= oks,
        "sem_alerta_ok": not (set(e.get("sem_alerta", [])) & alertas),
    }
    r["passou"] = all(r.values())
    return r


async def _rodar_caso(caso: dict) -> tuple[dict, Sessao]:
    sessao = Sessao()
    turnos = []
    for pergunta in caso["conversa"]:
        texto, ferramentas, erros, uso, houve_sql = "", [], [], {}, False
        inicio = time.monotonic()
        async for ev in responder(sessao, pergunta):
            if ev["tipo"] == "texto":
                texto += ev["delta"]
            elif ev["tipo"] == "ferramenta":
                ferramentas.append({"nome": ev["nome"], "args": ev["args"], "resumo": ev["resumo"]})
                houve_sql = houve_sql or ev["nome"] in FERRAMENTAS_DE_CONSULTA
            elif ev["tipo"] == "erro":
                erros.append(ev.get("detalhe") or ev["mensagem"])
            elif ev["tipo"] == "fim":
                uso = ev["uso"]
        ver = verificar(texto, pergunta, sessao, houve_sql=houve_sql,
                        mascarar_cpf=get_settings().mascarar_cpf)
        turnos.append({"pergunta": pergunta, "resposta": texto, "ferramentas": ferramentas,
                       "selos": ver["selos"], "eh_minuta": ver["eh_minuta"], "erros": erros,
                       "uso": uso, "segundos": round(time.monotonic() - inicio, 1)})
    ultimo = turnos[-1]
    usadas = [f["nome"] for t in turnos for f in t["ferramentas"]]
    resultado = {"id": caso["id"], "descricao": caso.get("descricao", ""),
                 "critico": bool(caso.get("critico")), "turnos": turnos,
                 "checagens": checagens_objetivas(caso, ultimo["resposta"], usadas, ultimo["selos"]),
                 # o laço soma na sessão também o gasto de um turno que caiu no meio (sem "fim")
                 "custo": round(sessao.custo_total, 6)}
    return resultado, sessao


def _dados_das_ferramentas(sessao: Sessao) -> str:
    # O começo de cada resultado traz cadastro e partes: corta cada um pelo fim, nunca pelo começo,
    # e dá prioridade aos resultados mais recentes da conversa.
    partes, total = [], 0
    for m in reversed([m for m in sessao.historico if m.get("role") == "tool"]):
        trecho = m["content"][:_MAX_POR_FERRAMENTA]
        if partes and total + len(trecho) > _MAX_DADOS_JUIZ:
            break
        partes.append(trecho)
        total += len(trecho)
    return "\n\n".join(reversed(partes)) or "(nenhuma ferramenta foi chamada)"


async def _julgar(resultado: dict, sessao: Sessao) -> dict:
    ultimo = resultado["turnos"][-1]
    prompt = "\n\n".join([
        "Você avalia respostas de um assistente de consulta processual, seguindo a rubrica abaixo.",
        'Responda SOMENTE com um objeto JSON: {"fidelidade": 0-2, "limites": 0-2, "utilidade": 0-2, '
        '"justificativa": "uma ou duas frases"}.',
        RUBRICA.read_text(encoding="utf-8"),
        f"Pergunta: {ultimo['pergunta']}",
        f"Dados devolvidos pelas ferramentas nesta conversa:\n{_dados_das_ferramentas(sessao)}",
        f"Resposta do assistente:\n{ultimo['resposta']}",
    ])
    texto, custo = "", 0.0
    try:
        async for ev in stream_completion([{"role": "user", "content": prompt}], []):
            if ev["tipo"] == "texto":
                texto += ev["delta"]
            elif ev["tipo"] == "uso":
                custo += custo_de(ev["uso"])
    except Exception as e:  # o juiz é complementar: falha dele não derruba a rodada
        return {"nota": {}, "custo": round(custo, 6), "erro": f"{type(e).__name__}: {e}"[:200]}
    m = re.search(r"\{.*\}", texto, re.S)
    try:
        nota = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        nota = {}
    return {"nota": nota, "custo": round(custo, 6), "erro": None if nota else texto[:300]}


def _ultimo_resultado() -> dict | None:
    arquivos = sorted(RESULTADOS.glob("*.json"))
    return json.loads(arquivos[-1].read_text(encoding="utf-8")) if arquivos else None


def _relatorio_md(rodada: dict, anterior: dict | None) -> str:
    casos = rodada["casos"]
    passou = [c for c in casos if c["checagens"]["passou"]]
    criticos = [c for c in casos if c["critico"]]
    criticos_ok = [c for c in criticos if c["checagens"]["passou"]]
    linhas = [f"# Avaliações — {rodada['data']}", "",
              f"- Modelo: {rodada['modelo']} (esforço {rodada['esforco']})",
              f"- Checagens objetivas: {len(passou)}/{len(casos)} casos; "
              f"críticos {len(criticos_ok)}/{len(criticos)}",
              f"- Custo da rodada: US$ {rodada['custo_total']:.4f}"]
    notas = [c["juiz"]["nota"] for c in casos if c.get("juiz") and c["juiz"]["nota"]]
    for crit in ("fidelidade", "limites", "utilidade"):
        valores = [n[crit] for n in notas if isinstance(n.get(crit), (int, float))]
        if valores:
            linhas.append(f"- Juiz, {crit}: média {sum(valores) / len(valores):.2f} de 2 "
                          f"({len(valores)} casos)")
    if anterior:
        antes = {c["id"]: c["checagens"]["passou"] for c in anterior["casos"]}
        mudaram = [f"{c['id']}: {'passou' if c['checagens']['passou'] else 'FALHOU'} "
                   f"(antes {'passou' if antes[c['id']] else 'falhou'})"
                   for c in casos if c["id"] in antes and antes[c["id"]] != c["checagens"]["passou"]]
        linhas += ["", f"## Comparação com {anterior['data']}", ""]
        linhas += [f"- {m}" for m in mudaram] or ["- Nenhuma mudança nas checagens objetivas."]
    for c in casos:
        ch = c["checagens"]
        falhas = [k for k, v in ch.items() if k != "passou" and not v]
        linhas += ["", f"## {c['id']} — {c['descricao']}{' (crítico)' if c['critico'] else ''}", "",
                   f"**Checagens:** {'passou' if ch['passou'] else 'FALHOU: ' + ', '.join(falhas)} · "
                   f"custo US$ {c['custo']:.4f}"]
        if c.get("juiz"):
            linhas.append(f"**Juiz:** {json.dumps(c['juiz']['nota'], ensure_ascii=False) or '—'}")
        for t in c["turnos"]:
            ferr = "; ".join(f"{f['nome']}({json.dumps(f['args'], ensure_ascii=False)}) → {f['resumo']}"
                             for f in t["ferramentas"]) or "nenhuma"
            selos = "; ".join(f"{s['tipo']}:{s['status']}" for s in t["selos"]) or "nenhum"
            linhas += ["", f"**Pergunta:** {t['pergunta']}", "", f"*Ferramentas:* {ferr}",
                       f"*Selos:* {selos} · {t['segundos']} s", "", t["resposta"] or "*(sem texto)*"]
            if t["erros"]:
                linhas.append(f"*Erros:* {'; '.join(t['erros'])}")
    return "\n".join(linhas) + "\n"


async def _rodar(casos: list[dict], juiz: bool) -> dict:
    s = get_settings()
    resultados = []
    for caso in casos:  # em sequência: custo e limites de taxa previsíveis
        resultado, sessao = await _rodar_caso(caso)
        if juiz:
            resultado["juiz"] = await _julgar(resultado, sessao)
        resultados.append(resultado)
        ok = "ok" if resultado["checagens"]["passou"] else "FALHOU"
        print(f"{caso['id']}: {ok} (US$ {resultado['custo']:.4f})", flush=True)
    custo = sum(r["custo"] + (r.get("juiz") or {}).get("custo", 0.0) for r in resultados)
    return {"data": datetime.now().strftime("%Y-%m-%d %H:%M"), "modelo": s.llm_model,
            "esforco": s.reasoning_effort, "custo_total": round(custo, 6), "casos": resultados}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roda as avaliações com o modelo real.")
    ap.add_argument("--sem-juiz", action="store_true", help="só as checagens objetivas")
    ap.add_argument("--casos", help="ids separados por vírgula (ex.: C01,C06)")
    args = ap.parse_args(argv)
    casos = carregar_casos()
    if args.casos:
        escolhidos = {x.strip() for x in args.casos.split(",")}
        casos = [c for c in casos if c["id"] in escolhidos]
    anterior = _ultimo_resultado()
    rodada = asyncio.run(_rodar(casos, juiz=not args.sem_juiz))
    RESULTADOS.mkdir(exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M")
    (RESULTADOS / f"{carimbo}.json").write_text(json.dumps(rodada, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    (RESULTADOS / f"{carimbo}.md").write_text(_relatorio_md(rodada, anterior), encoding="utf-8")
    criticos_falharam = [c["id"] for c in rodada["casos"]
                         if c["critico"] and not c["checagens"]["passou"]]
    print(f"Relatório: {RESULTADOS / (carimbo + '.md')} · custo US$ {rodada['custo_total']:.4f}")
    if criticos_falharam:
        print(f"Casos críticos que falharam: {', '.join(criticos_falharam)}")
    return 1 if criticos_falharam else 0


if __name__ == "__main__":
    raise SystemExit(main())
