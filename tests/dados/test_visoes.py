from app.dados.conexao import abrir_conexao


def um(c, sql, *a):
    return c.execute(sql, a).fetchone()


def test_situacao_normalizada():
    c = abrir_conexao()
    # 12 grafias colapsam em 4; 'julgado' é uma delas
    valores = {r[0] for r in c.execute("select distinct situacao from v_processo")}
    assert valores == {"Julgado", "Arquivado", "Em andamento", "Suspenso"}


def test_comarca_vem_da_unidade():
    c = abrir_conexao()
    # Joinville julgados: 190 pela unidade (não 168 pela grafia crua de processo.comarca)
    n = um(c, "select count(*) from v_processo where comarca = 'Joinville' and situacao = 'Julgado'")[0]
    assert n == 190


def test_partes_usa_polo_e_mascara_cpf():
    c = abrir_conexao()
    r = um(c, """select cpf_cnpj from v_partes
                 where numero = '0000001-15.2022.8.99.9012' and polo = 'ativo'""")
    assert r[0] == "***.550.862-**"


def test_documentos_extrai_advogado():
    c = abrir_conexao()
    r = um(c, """select advogado, oab from v_documentos
                 where numero = '0000001-15.2022.8.99.9012' and tipo = 'Petição Inicial'""")
    assert "Sebastião Krüger" in r[0]
    assert r[1] == "OAB/SC 99.651"


def test_movimentacoes_sem_orfas():
    c = abrir_conexao()
    total = um(c, "select count(*) from v_movimentacoes")[0]
    assert total == 134046 - 402  # exclui as 402 órfãs
