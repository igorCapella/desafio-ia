"""Reconfere as respostas REAIS de uma rodada com o verificador atual, sem chamar o modelo.

Refaz as consultas gravadas em cada turno (as ferramentas são determinísticas sobre o banco), remonta
a sessão e roda `verificar` de novo sobre a resposta gravada. Mostra, por turno, os alertas da época e
os de agora: é assim que se mede o efeito de uma mudança no verificador sem gastar uma nova rodada.

Uso: uv run python -m evals.reverificar evals/resultados/<rodada>.json
"""
import json
import sys
from pathlib import Path

from app.agente.sessao import Sessao
from app.dados.ferramentas import IMPL
from app.verificacao.citacoes import FERRAMENTAS_DE_CONSULTA
from app.verificacao.selos import verificar


def reverificar(rodada: dict) -> list[dict]:
    turnos = []
    for caso in rodada["casos"]:
        sessao = Sessao()
        for n, turno in enumerate(caso["turnos"], 1):
            sessao.registrar_pergunta(turno["pergunta"])
            for f in turno["ferramentas"]:
                extra = ({"cpfs_do_usuario": frozenset(sessao.cpfs_do_usuario)}
                         if f["nome"] == "buscar_processos" else {})
                res = IMPL[f["nome"]](**f["args"], **extra)
                sessao.registrar_resultado(f["nome"], res)
                if f["nome"] == "obter_dossie" and res.get("encontrado"):
                    p = res["processo"]
                    sessao.definir_foco(p["numero"], {"classe": p["classe"], "situacao": p["situacao"]})
            houve_sql = any(f["nome"] in FERRAMENTAS_DE_CONSULTA for f in turno["ferramentas"])
            agora = verificar(turno["resposta"], turno["pergunta"], sessao, houve_sql=houve_sql)
            turnos.append({"caso": caso["id"], "turno": n,
                           "antes": [s for s in turno["selos"] if s["status"] == "alerta"],
                           "agora": [s for s in agora["selos"] if s["status"] == "alerta"]})
    return turnos


def main(caminho: str) -> None:
    turnos = reverificar(json.loads(Path(caminho).read_text(encoding="utf-8")))
    for t in turnos:
        if t["antes"] or t["agora"]:
            print(f"{t['caso']} turno {t['turno']}: {len(t['antes'])} alerta(s) na época -> {len(t['agora'])} agora")
            for s in t["agora"]:
                print(f"   [{s['tipo']}] {s['mensagem']} {s['trechos'][:3]}")
    print(f"Total: {sum(len(t['antes']) for t in turnos)} alerta(s) na época -> "
          f"{sum(len(t['agora']) for t in turnos)} com o verificador atual")


if __name__ == "__main__":
    main(sys.argv[1])
