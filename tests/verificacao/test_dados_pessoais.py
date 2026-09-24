from app.verificacao.dados_pessoais import verificar_dados_pessoais


def test_cpf_completo_alerta_sem_repetir_o_cpf():
    selos = verificar_dados_pessoais("CPF 999.550.862-21 da autora.", True)
    assert selos[0]["status"] == "alerta" and selos[0]["trechos"] == ["***.550.862-**"]


def test_cpf_mascarado_ou_cnpj_nao_alerta():
    assert verificar_dados_pessoais("CPF ***.550.862-**; CNPJ 99.076.775/0001-59.", True) == []


def test_cpf_digitado_pelo_usuario_nao_alerta():
    assert verificar_dados_pessoais("CPF 999.550.862-21.", True, {"99955086221"}) == []


def test_sem_mascara_configurada_nao_verifica():
    assert verificar_dados_pessoais("CPF 999.550.862-21.", False) == []
