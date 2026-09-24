import hashlib
from app.dados.conexao import (
    abrir_conexao, SHA256_ESPERADO, py_mascarar_cpf, py_oab_de, py_normalizar,
    py_advogado_de, verificar_integridade,
)


def test_banco_integro():
    with open("data/desafio.sqlite", "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert digest == SHA256_ESPERADO


def test_conexao_e_readonly():
    c = abrir_conexao()
    try:
        c.execute("create table x(a)")
        assert False, "deveria ser somente leitura"
    except Exception as e:
        assert "readonly" in str(e).lower() or "read-only" in str(e).lower()


def test_funcoes_sql():
    c = abrir_conexao()
    assert c.execute("select normalizar('  SÃO  José ')").fetchone()[0] == "sao jose"
    assert c.execute("select oab_de('Dr. X — OAB/SC 99.651')").fetchone()[0] == "OAB/SC 99.651"
    assert c.execute("select mascarar_cpf('999.550.862-21')").fetchone()[0] == "***.550.862-**"


def test_funcoes_python_espelham():
    assert py_normalizar("SÃO José") == "sao jose"
    assert py_oab_de("Dra. Y — OAB/SC 99.154") == "OAB/SC 99.154"
    assert py_mascarar_cpf("999.550.862-21") == "***.550.862-**"


def test_banco_integro_pela_funcao():
    assert verificar_integridade("data/desafio.sqlite") is True


def test_mascarar_cpf_fail_closed():
    assert py_mascarar_cpf("99955086221") == "***.550.862-**"
    assert py_mascarar_cpf(" 999.550.862-21 ") == "***.550.862-**"
    assert py_mascarar_cpf("99.549.809/0001-93") == "99.549.809/0001-93"
    assert py_mascarar_cpf("999.550.862-21 / x") == "***.***.***-** / x"
    assert py_mascarar_cpf(None) is None
    assert py_mascarar_cpf("") == ""


def test_advogado_de():
    assert py_advogado_de("Dr. Sebastião Krüger — OAB/SC 99.651") == "Dr. Sebastião Krüger"
    assert py_advogado_de("Dr. Mário Pacheco Heusi — Promotor(a) de Justiça") is None
    assert py_advogado_de(None) is None
