from contextlib import closing

import pytest

from app.dados.conexao import abrir_conexao, abrir_conexao_consulta


@pytest.fixture
def conn():
    with closing(abrir_conexao()) as c:
        yield c


@pytest.fixture
def conn_consulta():
    with closing(abrir_conexao_consulta()) as c:
        yield c
