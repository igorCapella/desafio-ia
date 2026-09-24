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
