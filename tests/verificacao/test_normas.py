from app.verificacao.normas import verificar_normas

DOCS = {93: "... nos termos do art. 373, inciso I, do Código de Processo Civil ..."}


def test_norma_nos_autos_ok():
    assert all(s["status"] == "ok" for s in verificar_normas("Aplica-se o art. 373 do CPC.", DOCS))


def test_sumula_externa_alerta():
    selos = verificar_normas("Incide a Súmula 403 do STJ.", DOCS)
    assert any(s["status"] == "alerta" and "403" in " ".join(s["trechos"]) for s in selos)


def test_marcada_verificar_nao_alerta():
    selos = verificar_normas("Talvez a Súmula 385 do STJ [verificar].", DOCS)
    assert all(s["status"] != "alerta" for s in selos)


def test_artigo_marcado_verificar_nao_alerta():
    r = "Aplica-se também o art. 999 do Código de Processo Civil, conforme [verificar]."
    assert all(s["status"] != "alerta" for s in verificar_normas(r, DOCS))


def test_verificar_em_outra_linha_nao_vale():
    r = "Incide a Súmula 403 do STJ.\n[verificar] outra coisa"
    assert any(s["status"] == "alerta" for s in verificar_normas(r, DOCS))

def test_lista_de_artigos_e_prefixo_de_numero():
    docs = {1: "com base nos arts. 485 e 487 do CPC e no artigo 52 da lei"}
    assert all(s["status"] == "ok" for s in verificar_normas("Aplicam-se os arts. 485 e 487.", docs))
    alerta = verificar_normas("Conforme o artigo 5º da Constituição.", docs)[0]
    assert alerta["status"] == "alerta" and alerta["trechos"] == ["art. 5"]


def test_lista_de_artigos_inventados_alerta():
    selos = verificar_normas("Aplicam-se os arts. 485 e 487.", {1: "sem artigos aqui"})
    assert selos[0]["trechos"] == ["art. 485", "art. 487"]


def test_verificar_antes_da_referencia_vale():
    selos = verificar_normas("Conforme [verificar] a Súmula 403 do STJ.", DOCS)
    assert all(s["status"] != "alerta" for s in selos)


def test_norma_que_esta_nas_movimentacoes_nao_alerta():
    mov = ['{"movimentacoes": [{"data": "2024-01-10", '
           '"descricao": "Arquivamento Provisório (art. 40 LEF)"}]}']
    r = "O processo foi arquivado provisoriamente com base no art. 40 da LEF."
    assert [s["status"] for s in verificar_normas(r, DOCS)] == ["alerta"]
    assert [s["status"] for s in verificar_normas(r, DOCS, mov)] == ["ok"]


def test_marca_verificar_com_explicacao_tambem_vale():
    r = "Aplicável o art. 485 do CPC [verificar — dispositivo não citado nos autos]."
    assert all(s["status"] != "alerta" for s in verificar_normas(r, DOCS))
    assert any(s["status"] == "alerta" for s in verificar_normas("Aplicável o art. 485 do CPC.", DOCS))
