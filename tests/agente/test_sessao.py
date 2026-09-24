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


def test_obter_sessao_reusa_e_ignora_id_invalido():
    sid = nova_sessao()
    assert obter_sessao(sid) is obter_sessao(sid)
    avulsa = obter_sessao("não-é-um-id")
    assert isinstance(avulsa, Sessao) and "não-é-um-id" not in S.SESSOES


def test_limite_de_sessoes_descarta_a_mais_antiga(monkeypatch):
    monkeypatch.setattr(S, "SESSOES", S.OrderedDict())
    monkeypatch.setattr(S, "_MAX_SESSOES", 3)
    ids = [nova_sessao() for _ in range(5)]
    assert list(S.SESSOES) == ids[2:]
