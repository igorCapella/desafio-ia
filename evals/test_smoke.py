from contextlib import closing

from app.dados.conexao import abrir_conexao
from evals.executar import carregar_casos, checagens_objetivas

_CHAVES_ESPERA = {"fatos", "nao_deve", "ferramentas", "selos_ok", "sem_alerta"}


def test_casos_bem_formados():
    casos = carregar_casos()
    assert len(casos) >= 20
    ids = [c["id"] for c in casos]
    assert len(ids) == len(set(ids))
    for c in casos:
        assert c["id"] and c["conversa"] and "espera" in c
        assert set(c["espera"]) <= _CHAVES_ESPERA, c["id"]
    assert sum(bool(c.get("critico")) for c in casos) >= 10


def test_gabaritos_conferem_com_o_banco():
    with closing(abrir_conexao()) as conn:
        for c in carregar_casos():
            for g in c.get("gabarito", []):
                valor = conn.execute(g["sql"]).fetchone()[0]
                assert valor == g["espera"], (c["id"], g["sql"], valor)


def test_checagem_objetiva():
    caso = {"espera": {"fatos": ["190", "Joinville | Joinvile"], "nao_deve": ["168"],
                       "ferramentas": ["consultar_sql"], "selos_ok": ["citacao"],
                       "sem_alerta": ["processo"]}}
    selos = [{"tipo": "citacao", "status": "ok"}, {"tipo": "norma", "status": "ok"}]
    r = checagens_objetivas(caso, "São 190 processos em JOINVILLE [SQL].", ["consultar_sql"], selos)
    assert r["passou"] is True
    r = checagens_objetivas(caso, "São 168 processos.", ["obter_dossie"],
                            [{"tipo": "processo", "status": "alerta"}])
    assert not any(r[k] for k in ("fatos_ok", "nao_deve_ok", "ferramentas_ok", "selos_ok",
                                  "sem_alerta_ok", "passou"))
