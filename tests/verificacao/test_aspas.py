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


def test_aspas_do_cadastro_sao_literais_mas_nao_viram_link_de_documento():
    cadastro = ['{"assunto": "Inclusão Indevida em Cadastro de Inadimplentes"}']
    selos = verificar_aspas('O assunto é "Inclusão Indevida em Cadastro de Inadimplentes".',
                            DOCS, cadastro)
    assert [s["status"] for s in selos] == ["ok"]
    assert selos[0]["docs"] == [] and selos[0]["trechos_das_ferramentas"]


def test_texto_entre_duas_citacoes_nao_vira_citacao():
    r = 'A "sentença" foi citada e, depois de um longo trecho sem aspas nenhumas, o "réu" recorreu.'
    assert verificar_aspas(r, DOCS) == []


def test_aviso_da_minuta_entre_aspas_nao_e_citacao():
    r = 'A minuta começa com o aviso "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA PROFERIDA".'
    assert verificar_aspas(r, DOCS) == []


def test_aspas_que_repetem_a_pergunta_nao_sao_aprovadas_nem_alertadas():
    perguntas = ["Qual é a jurisprudência do STJ sobre dano moral por negativação indevida?"]
    r = 'Busquei "dano moral por negativação indevida" e nada encontrei.'
    assert [s["status"] for s in verificar_aspas(r, DOCS)] == ["alerta"]
    assert verificar_aspas(r, DOCS, perguntas=perguntas) == []


def test_trecho_que_comeca_no_meio_de_uma_palavra_nao_e_literal():
    docs = {93: "Ante o exposto, JULGO IMPROCEDENTE o pedido formulado na inicial."}
    trocado = verificar_aspas('Decidiu "procedente o pedido formulado na inicial".', docs)
    assert [s["status"] for s in trocado] == ["alerta"]  # "procedente" não é literal de "improcedente"
    certo = verificar_aspas('Decidiu "improcedente o pedido formulado na inicial".', docs)
    assert [s["status"] for s in certo] == ["ok"]
