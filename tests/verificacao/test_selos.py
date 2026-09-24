from app.agente.sessao import Sessao
from app.verificacao.minuta import AVISO
from app.verificacao.selos import verificar

NUM = "0000001-15.2022.8.99.9012"


def _sessao():
    s = Sessao()
    s.definir_foco(NUM, {"classe": "c", "situacao": "Arquivado"})
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": NUM, "magistrado": "Daiane Duarte Zanella",
                     "situacao": "Arquivado", "data_sentenca": "2024-08-26"},
        "documentos": [{"id": 93, "tipo": "Sentença", "texto": "Julgo improcedente o pedido."}],
        "movimentacoes": [{"data": "2024-09-30", "descricao": "Trânsito em Julgado"}]})
    return s


def test_reune_selos_e_marca_minuta():
    r = (f"{AVISO}\n\nEste processo já foi julgado [Doc 93 – Sentença, 26/08/2024] "
         f"[Mov 30/09/2024 – Trânsito em Julgado]. Confirma que deseja uma nova minuta "
         f"do {NUM}?")
    res = verificar(r, "Elabore uma minuta", _sessao(), houve_sql=False)
    assert res["eh_minuta"] is True
    assert {"citacao", "minuta", "processo"} <= {s["tipo"] for s in res["selos"]}
    assert all(s["status"] == "ok" for s in res["selos"])


def test_minuta_de_processo_julgado_sem_aviso_alerta():
    r = (f"{AVISO}\n\n## I – RELATÓRIO\nTrata-se de ação.\n\n## III – DISPOSITIVO\n"
         "Ante o exposto, [JULGO PROCEDENTE / IMPROCEDENTE].")
    res = verificar(r, "Redija a minuta", _sessao(), houve_sql=False)
    assert any(s["tipo"] == "minuta" and s["status"] == "alerta" for s in res["selos"])


def test_numero_da_pergunta_conta_como_conhecido():
    outro = "0009999-69.2024.8.99.9001"
    res = verificar(f"O processo {outro} não foi encontrado.", f"E o {outro}?", Sessao(),
                    houve_sql=False)
    assert all(s["status"] == "ok" for s in res["selos"])


def test_aspas_do_nao_encontrado_sao_literais_e_as_da_pergunta_ficam_de_fora():
    s = Sessao()
    pergunta = "Há jurisprudência sobre negativação indevida no STJ? E o 0009999-69.2024.8.99.9001?"
    s.registrar_pergunta(pergunta)
    s.registrar_resultado("obter_dossie", {"encontrado": False, "numero": "0009999-69.2024.8.99.9001",
                                           "erro": "Processo não encontrado no banco."})
    r = ('Sobre "negativação indevida no STJ", o banco não tem jurisprudência; o 0009999-69.2024.'
         '8.99.9001 deu "Processo não encontrado no banco".')
    aspas = [x for x in verificar(r, pergunta, s, houve_sql=False)["selos"] if x["tipo"] == "aspas"]
    # O "não encontrado" é resultado de ferramenta: literal. A pergunta é do usuário: fica de fora.
    assert [(x["status"], x["trechos_das_ferramentas"]) for x in aspas] == [
        ("ok", ["Processo não encontrado no banco"])]


def test_decisao_de_outro_processo_da_conversa_entre_aspas_alerta():
    s = _sessao()  # processo NUM, julgado, com a sentença Doc 93 "Julgo improcedente o pedido."
    outro = "0000001-81.2023.8.99.9011"
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": outro, "magistrado": None, "situacao": "Em andamento",
                     "data_sentenca": None},
        "documentos": [{"id": 940, "tipo": "Petição Inicial", "texto": "Requer a procedência."}],
        "movimentacoes": []})
    s.definir_foco(outro, {"classe": "c", "situacao": "Em andamento"})
    r = (f"{AVISO}\n\nRELATÓRIO\nTrata-se de ação.\n\nFUNDAMENTAÇÃO\nAnalisa-se.\n\n"
         'DISPOSITIVO\n"Julgo improcedente o pedido."')
    res = verificar(r, "Elabore a minuta de sentença", s, houve_sql=False)
    assert any("decisão de mérito" in x["mensagem"] for x in res["selos"] if x["status"] == "alerta")


def test_norma_citada_das_movimentacoes_confere():
    s = Sessao()
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": NUM, "magistrado": None, "situacao": "Suspenso", "data_sentenca": None},
        "documentos": [{"id": 31, "tipo": "Petição Inicial", "texto": "Execução fiscal de ISS."}],
        "movimentacoes": [{"data": "2024-03-01",
                           "descricao": "Arquivamento Provisório (art. 40 LEF)"}]})
    res = verificar("Arquivado provisoriamente com base no art. 40 da LEF.", "Resuma", s,
                    houve_sql=False)
    assert [x["status"] for x in res["selos"] if x["tipo"] == "norma"] == ["ok"]


def test_citacao_nao_emenda_dois_campos_do_cadastro():
    s = Sessao()
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": NUM, "assunto": "Cobrança de honorários", "comarca": "Capital"},
        "documentos": [], "movimentacoes": []})
    res = verificar('O cadastro diz "Cobrança de honorários Capital".', "Resuma", s, houve_sql=False)
    assert [x["status"] for x in res["selos"] if x["tipo"] == "aspas"] == ["alerta"]


def test_minuta_redigida_depois_da_confirmacao_continua_sendo_minuta():
    s = _sessao()  # processo julgado, com a sentença Doc 93
    aviso = verificar("Este processo já foi julgado [Doc 93]. Confirma que deseja uma nova minuta?",
                      "Elabore uma minuta de sentença", s, houve_sql=False)
    assert aviso["eh_minuta"] is True
    r = ("RELATÓRIO\nTrata-se de ação.\n\nFUNDAMENTAÇÃO\nAnalisa-se.\n\nDISPOSITIVO\n"
         "Ante o exposto, [JULGO PROCEDENTE / IMPROCEDENTE] o pedido.")
    res = verificar(r, "Sim, confirmo. Pode redigir.", s, houve_sql=False)
    assert res["eh_minuta"] is True
    assert any("aviso" in x["mensagem"] for x in res["selos"] if x["status"] == "alerta")


def test_secoes_sem_pedido_nem_minuta_anterior_nao_viram_minuta():
    r = ("RELATÓRIO\nA sentença relatou.\n\nFUNDAMENTAÇÃO\nFundamentou.\n\nDISPOSITIVO\n"
         "Julgou improcedente.")
    assert verificar(r, "Resuma a sentença", _sessao(), houve_sql=False)["eh_minuta"] is False
