import json

from app.dados import ferramentas as F


def test_dossie_processo_completo():
    r = F.obter_dossie("0000001-15.2022.8.99.9012")
    assert r["encontrado"] is True
    assert len(r["documentos"]) == 8
    assert any("Krüger" in adv["nome"] for adv in r["advogados"])
    assert r["alertas"] == []


def test_dossie_polo_inferido_com_base():
    r = F.obter_dossie("0000001-15.2022.8.99.9012")
    kruger = next(a for a in r["advogados"] if "Krüger" in a["nome"])
    assert kruger["polo_inferido"] == "ativo"
    assert "Doc 86 – Petição Inicial" in kruger["base_inferencia"]


def test_dossie_numero_dv_invalido():
    r = F.obter_dossie("0000001-16.2022.8.99.9012")
    assert r["encontrado"] is False
    assert "verificador" in r["erro"].lower()


def test_dossie_inexistente():
    r = F.obter_dossie("0009999-69.2024.8.99.9001")  # DV válido, não existe
    assert r["encontrado"] is False
    assert "não encontrado" in r["erro"].lower()


def test_busca_por_parte():
    r = F.buscar_processos(parte="Financeira Araucária")
    assert r["total"] >= 1
    assert len(r["processos"]) <= 20


def test_busca_por_cpf_completo_mesmo_com_mascara():
    for doc in ("999.550.862-21", "99955086221"):
        r = F.buscar_processos(cpf_cnpj=doc)
        assert r["total"] == 1
        assert r["processos"][0]["numero"] == "0000001-15.2022.8.99.9012"
        assert "550.862" not in json.dumps(r, ensure_ascii=False)


def test_busca_cpf_incompleto_pede_numero_completo():
    assert "erro" in F.buscar_processos(cpf_cnpj="550.862")


def test_sql_agregado_ok():
    r = F.consultar_sql(
        "select count(*) as n from v_processo where comarca='Joinville' and situacao='Julgado'")
    assert r["linhas"][0][0] == 190
    assert "duracao_ms" in r


def test_sql_cte_recursiva_ok():
    r = F.consultar_sql("with recursive r(n) as (select 1 union all select n + 1 from r "
                        "where n < 5) select count(*) from r")
    assert r["linhas"] == [[5]]


def test_sql_bloqueia_tabela_base():
    r = F.consultar_sql("select count(*) from processo")
    assert "erro" in r
    assert "v_processo" in r["erro"]  # orienta o modelo, em português


def test_sql_cte_nao_alcanca_dado_cru():
    for sql in ("with x as (select documento from parte) select * from x",
                "with v_partes as (select documento as cpf_cnpj from parte) "
                "select * from v_partes"):
        assert "erro" in F.consultar_sql(sql)


def test_sql_nenhum_cpf_completo():
    r = F.consultar_sql("select count(*) from v_partes where cpf_cnpj glob "
                        "'[0-9][0-9][0-9].[0-9][0-9][0-9].[0-9][0-9][0-9]-[0-9][0-9]'")
    assert r["linhas"] == [[0]]


def test_sql_bloqueia_escrita():
    for sql in ("delete from processo", "delete from v_processo", "create table x(a)"):
        assert "erro" in F.consultar_sql(sql)


def test_sql_bloqueia_attach_e_pragma():
    for sql in ("attach database 'data/desafio.sqlite' as orig", "pragma query_only = off"):
        assert "erro" in F.consultar_sql(sql)


def test_sql_um_comando():
    r = F.consultar_sql("select 1; drop table processo")
    assert "erro" in r


def test_sql_interrompe_por_tempo(monkeypatch):
    monkeypatch.setattr(F, "_TIMEOUT_S", 0.0)
    r = F.consultar_sql("select count(*) from v_movimentacoes a, v_unidades b")
    assert "interrompida" in r["erro"]
