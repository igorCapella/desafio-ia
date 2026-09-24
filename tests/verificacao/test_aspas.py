from app.verificacao.aspas import verificar_aspas

DOCS = {93: "A parte autora não se desincumbiu do ônus de comprovar os fatos constitutivos.",
        89: "Requer a improcedência total dos pedidos formulados na inicial."}


def test_aspas_literais_ok_e_indica_o_documento():
    r = 'A juíza afirmou: "não se desincumbiu do ônus de comprovar os fatos constitutivos".'
    selos = verificar_aspas(r, DOCS)
    assert [s["status"] for s in selos] == ["ok"]
    assert selos[0]["docs"] == [93]


def test_parafrase_alerta():
    r = 'A juíza disse que "a autora não provou nada do que alegou na inicial".'
    assert any(s["status"] == "alerta" for s in verificar_aspas(r, DOCS))


def test_reticencias_juntam_fragmentos_do_mesmo_documento():
    r = 'Consta: "A parte autora não se desincumbiu … de comprovar os fatos constitutivos".'
    assert [s["status"] for s in verificar_aspas(r, DOCS)] == ["ok"]


def test_fragmentos_de_documentos_diferentes_nao_contam_como_literal():
    r = '"A parte autora não se desincumbiu... improcedência total dos pedidos formulados"'
    assert any(s["status"] == "alerta" for s in verificar_aspas(r, DOCS))

def test_aspas_curvas_tambem_sao_conferidas():
    r = "A juíza afirmou: “não se desincumbiu do ônus de comprovar os fatos constitutivos”."
    assert [s["status"] for s in verificar_aspas(r, DOCS)] == ["ok"]


def test_parafrase_entre_aspas_curvas_alerta():
    r = "A juíza disse que “a autora não provou nada do que alegou na inicial”."
    assert any(s["status"] == "alerta" for s in verificar_aspas(r, DOCS))

def test_aspas_dentro_de_codigo_nao_sao_citacao():
    # Caso real do log: o texto ENTRE duas aspas de trechos de código diferentes virava "citação".
    r = ('Consultei `buscar_processos(cpf_cnpj="123.456.789-09")` → total 0; '
         '`buscar_processos(cpf_cnpj="12345678909")` → total 0.')
    assert verificar_aspas(r, DOCS) == []

