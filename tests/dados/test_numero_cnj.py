from app.dados.numero_cnj import normalizar_numero


def test_aceita_com_pontuacao():
    n, erro = normalizar_numero("0000001-15.2022.8.99.9012")
    assert erro is None
    assert n == "0000001-15.2022.8.99.9012"


def test_aceita_sem_pontuacao():
    n, erro = normalizar_numero("00000011520228999012")
    assert erro is None
    assert n == "0000001-15.2022.8.99.9012"


def test_digito_verificador_errado():
    n, erro = normalizar_numero("0000001-16.2022.8.99.9012")
    assert n == "0000001-16.2022.8.99.9012"
    assert "verificador" in erro.lower()
    assert "15" in erro  # informa o DV correto


def test_formato_invalido():
    n, erro = normalizar_numero("123")
    assert n is None
    assert "20 díg" in erro or "20 dig" in erro.lower()
