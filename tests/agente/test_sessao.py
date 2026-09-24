from app.agente import sessao as S
from app.agente.sessao import Sessao, nova_sessao, obter_sessao


def test_linha_de_contexto_sem_foco():
    s = Sessao()
    assert "nenhum" in s.linha_de_contexto().lower()


def test_definir_foco():
    s = Sessao()
    s.definir_foco("0000001-15.2022.8.99.9012",
                   {"classe": "Procedimento Comum Cível", "situacao": "Julgado"})
    linha = s.linha_de_contexto()
    assert "0000001-15.2022.8.99.9012" in linha
    assert "Julgado" in linha


def test_compactar_dossie_antigo():
    s = Sessao()
    # dossiê grande no histórico, como resultado de ferramenta
    s.adicionar({"role": "tool", "tool_call_id": "a", "name": "obter_dossie",
                 "content": "x" * 5000, "_numero": "0000001-15.2022.8.99.9012"})
    s.definir_foco("0000002-97.2022.8.99.9012", {"classe": "c", "situacao": "Em andamento"})
    s.compactar_dossies_antigos()
    alvo = [m for m in s.historico if m.get("_numero") == "0000001-15.2022.8.99.9012"][0]
    assert "omitido" in alvo["content"]
    assert len(alvo["content"]) < 200


def test_compactacao_nao_depende_do_texto_do_dossie():
    s = Sessao()
    s.adicionar({"role": "tool", "tool_call_id": "a", "name": "obter_dossie",
                 "content": '{"texto": "ponto omitido na sentença"}',
                 "_numero": "0000001-15.2022.8.99.9012"})
    s.definir_foco("0000002-97.2022.8.99.9012", {"classe": "c", "situacao": "Em andamento"})
    s.compactar_dossies_antigos()
    assert s.historico[0]["content"].startswith("[dossiê de 0000001-15.2022.8.99.9012 omitido")


def test_dossie_do_foco_atual_fica_inteiro():
    s = Sessao()
    s.adicionar({"role": "tool", "tool_call_id": "a", "name": "obter_dossie",
                 "content": "x" * 5000, "_numero": "0000001-15.2022.8.99.9012"})
    s.definir_foco("0000001-15.2022.8.99.9012", {"classe": "c", "situacao": "Julgado"})
    s.compactar_dossies_antigos()
    assert len(s.historico[0]["content"]) == 5000


def test_obter_sessao_reusa_e_ignora_id_invalido(monkeypatch):
    monkeypatch.setattr(S, "SESSOES", S.OrderedDict())
    sid = nova_sessao()
    assert obter_sessao(sid) is obter_sessao(sid)
    avulsa = obter_sessao("não-é-um-id")
    assert isinstance(avulsa, Sessao) and "não-é-um-id" not in S.SESSOES


def test_limite_de_sessoes_descarta_a_mais_antiga(monkeypatch):
    monkeypatch.setattr(S, "SESSOES", S.OrderedDict())
    monkeypatch.setattr(S, "_MAX_SESSOES", 3)
    ids = [nova_sessao() for _ in range(5)]
    assert list(S.SESSOES) == ids[2:]


def test_compactar_respeita_o_limite_do_turno():
    s = Sessao()
    s.adicionar({"role": "tool", "name": "obter_dossie", "content": "a" * 50, "_numero": "A"})
    s.adicionar({"role": "tool", "name": "obter_dossie", "content": "b" * 50, "_numero": "B"})
    s.definir_foco("C", {})
    s.compactar_dossies_antigos(ate=1)
    assert "omitido" in s.historico[0]["content"] and s.historico[1]["content"] == "b" * 50


def test_registrar_pergunta_guarda_cpfs_digitados():
    s = Sessao()
    s.registrar_pergunta("Processos do CPF 999.550.862-21 e do 12345678901? "
                         "Veja o 0000001-15.2022.8.99.9012")
    assert s.cpfs_do_usuario == {"99955086221", "12345678901"}


def test_registrar_resultado_acumula_fontes_da_conversa():
    s = Sessao()
    s.registrar_resultado("obter_dossie", {
        "encontrado": True, "processo": {"numero": "0000001-15.2022.8.99.9012"},
        "documentos": [{"id": 86, "texto": "petição"}],
        "movimentacoes": [{"data": "2022-01-10", "descricao": "Distribuição por Sorteio"}]})
    s.registrar_resultado("buscar_processos",
                          {"processos": [{"numero": "0000002-97.2022.8.99.9012"}]})
    s.registrar_resultado("consultar_sql", {"linhas": [["0000003-78.2023.8.99.9002", 5]]})
    assert s.docs_vistos == {86: "petição"}
    assert ("2022-01-10", "Distribuição por Sorteio") in s.movs_vistas
    assert s.processos_consultados == {"0000001-15.2022.8.99.9012",
                                       "0000002-97.2022.8.99.9012",
                                       "0000003-78.2023.8.99.9002"}


def test_registrar_pergunta_limita_cpfs_por_conversa():
    s = Sessao()
    s.registrar_pergunta(" ".join(f"{i:011d}" for i in range(1, 26)))
    assert len(s.cpfs_do_usuario) == 20


def test_registrar_resultado_guarda_resumo_e_numero_nao_encontrado():
    s = Sessao()
    s.registrar_resultado("obter_dossie", {"encontrado": False,
                                           "numero": "0009999-69.2024.8.99.9001",
                                           "erro": "Processo não encontrado no banco."})
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": "0000001-15.2022.8.99.9012", "magistrado": "X",
                     "situacao": "Arquivado", "data_sentenca": "2024-08-26"},
        "documentos": [{"id": 93, "tipo": "Sentença", "texto": "t"},
                       {"id": 86, "tipo": "Petição Inicial", "texto": "p"}],
        "movimentacoes": []})
    assert "0009999-69.2024.8.99.9001" in s.processos_consultados
    assert s.resumos["0000001-15.2022.8.99.9012"] == {
        "magistrado": "X", "situacao": "Arquivado", "data_sentenca": "2024-08-26",
        "n_documentos": 2, "sentencas": [93]}


def test_registrar_resultado_guarda_texto_do_cadastro_sem_documentos():
    s = Sessao()
    s.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": "0000001-15.2022.8.99.9012", "assunto": "Assunto Muito Específico"},
        "documentos": [{"id": 86, "tipo": "Petição Inicial", "texto": "TEXTO DO DOCUMENTO"}],
        "movimentacoes": []})
    assert "Assunto Muito Específico" in s.textos_cadastro[0]
    assert "TEXTO DO DOCUMENTO" not in s.textos_cadastro[0]
