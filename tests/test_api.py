import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.verificacao.minuta import AVISO

NUM = "0000001-15.2022.8.99.9012"
FIM = {"tipo": "fim", "uso": {"prompt": 10, "completion": 5, "raciocinio": 2, "cost": 0.001,
                              "modelo": "deepseek/deepseek-v4.1-flash", "provedor": "Makora",
                              "latencia_ms": 12.5}}


def _eventos(corpo: str) -> list[tuple[str, dict]]:
    """Converte o corpo SSE em [(evento, dados)]."""
    eventos, nome, dados = [], None, []
    for linha in corpo.splitlines() + [""]:
        if linha.startswith("event:"):
            nome = linha[6:].strip()
        elif linha.startswith("data:"):
            dados.append(linha[5:].strip())
        elif not linha.strip() and nome:
            eventos.append((nome, json.loads("\n".join(dados)) if dados else {}))
            nome, dados = None, []
    return eventos


def _fake(*eventos, preparo=None):
    async def responder(sessao, pergunta, **kw):
        if preparo:
            preparo(sessao)
        for ev in eventos:
            yield ev
    return responder


def _com_doc_93(sessao):
    sessao.registrar_resultado("obter_dossie", {
        "encontrado": True,
        "processo": {"numero": NUM, "magistrado": None, "situacao": "Arquivado",
                     "data_sentenca": None},
        "documentos": [{"id": 93, "tipo": "Sentença",
                        "texto": "trecho literal do documento noventa e três"}],
        "movimentacoes": []})
    sessao.custo_total += 0.001  # o laço real soma o custo do turno na sessão


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "AUDITORIA", str(tmp_path / "aud.jsonl"))
    with TestClient(main.app) as c:  # "with" roda o lifespan (validação do banco)
        yield c


def _sid(c):
    return c.post("/api/sessao/nova").json()["sessao_id"]


def _chat(c, sid, pergunta="x"):
    with c.stream("POST", "/api/chat", json={"sessao_id": sid, "pergunta": pergunta}) as r:
        assert r.status_code == 200
        return _eventos("".join(r.iter_text()))


def _ultima_auditoria():
    return json.loads(Path(main.AUDITORIA).read_text(encoding="utf-8").strip().splitlines()[-1])


def test_saude_sem_segredos(cliente):
    r = cliente.get("/api/saude")
    assert r.status_code == 200 and r.json()["ok"] is True
    chave = main.get_settings().openrouter_api_key
    assert "api_key" not in r.text and (not chave or chave not in r.text)


def test_chat_emite_eventos_e_verifica(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake(
        {"tipo": "status", "fase": "pensando"},
        {"tipo": "ferramenta", "nome": "obter_dossie", "args": {"numero": NUM},
         "duracao_ms": 1.5, "resumo": "1 docs, 0 alerta(s)"},
        {"tipo": "texto", "delta": 'Cita [Doc 93]: "trecho literal do documento noventa e três".'},
        FIM, preparo=_com_doc_93))
    eventos = _chat(cliente, _sid(cliente))
    assert [n for n, _ in eventos] == ["status", "ferramenta", "texto", "status", "verificacao",
                                       "fim"]
    assert eventos[3][1] == {"fase": "verificando"}
    selos = eventos[4][1]["selos"]
    assert {(s["tipo"], s["status"]) for s in selos} >= {("citacao", "ok"), ("aspas", "ok")}
    assert eventos[4][1]["aviso"] is None
    assert eventos[5][1]["custo_sessao"] == 0.001


def test_auditoria_registra_o_turno(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake(
        {"tipo": "ferramenta", "nome": "obter_dossie", "args": {"numero": NUM},
         "duracao_ms": 1.5, "resumo": "1 docs, 0 alerta(s)"},
        {"tipo": "texto", "delta": "Resumo [Doc 93]."}, FIM, preparo=_com_doc_93))
    sid = _sid(cliente)
    _chat(cliente, sid, "Resuma o processo do CPF 999.550.862-21")
    linha = _ultima_auditoria()
    assert linha["sessao"] == sid and "***.550.862-**" in linha["pergunta"]
    assert linha["ferramentas"] == [{"nome": "obter_dossie", "args": {"numero": NUM},
                                     "duracao_ms": 1.5, "resumo": "1 docs, 0 alerta(s)"}]
    assert (linha["modelo"], linha["provedor"]) == ("deepseek/deepseek-v4.1-flash", "Makora")
    assert linha["tokens"] == {"prompt": 10, "completion": 5, "raciocinio": 2}
    assert linha["custo"] == 0.001 and linha["latencia_ms"] == 12.5
    assert linha["selos"] and linha["erros"] == [] and linha["interrompida"] is False
    assert linha["resposta"] == "Resumo [Doc 93]." and linha["eh_minuta"] is False


def test_teto_de_orcamento(cliente, monkeypatch):
    chamado = []

    async def responder(sessao, pergunta, **kw):
        chamado.append(True)
        yield FIM

    monkeypatch.setattr(main, "responder", responder)
    monkeypatch.setattr(main, "custo_acumulado", lambda caminho=None: 999.0)
    eventos = _chat(cliente, _sid(cliente))
    assert eventos[0][0] == "erro" and "Orçamento" in eventos[0][1]["mensagem"]
    assert chamado == []


def test_erro_vai_para_a_tela_sem_detalhe_e_para_o_log_com_detalhe(cliente, monkeypatch):
    msg = "Não foi possível obter a resposta do modelo agora. Tente de novo."
    monkeypatch.setattr(main, "responder", _fake(
        {"tipo": "erro", "mensagem": msg, "detalhe": "HTTP 502: bad gateway"}))
    eventos = _chat(cliente, _sid(cliente))
    assert ("erro", {"mensagem": msg}) in eventos
    assert _ultima_auditoria()["erros"][0]["detalhe"] == "HTTP 502: bad gateway"


def test_falha_na_verificacao_nao_derruba_o_fim(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM))

    def quebra(*a, **k):
        raise TypeError("boom")

    monkeypatch.setattr(main, "verificar", quebra)
    eventos = dict(_chat(cliente, _sid(cliente)))
    assert eventos["verificacao"]["selos"][0]["tipo"] == "sistema"
    assert "fim" in eventos
    assert _ultima_auditoria()["erros"][0]["detalhe"] == "TypeError: boom"


def test_minuta_envia_o_aviso_da_interface(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "Confirme."}, FIM))
    eventos = dict(_chat(cliente, _sid(cliente), "Elabore uma minuta de sentença"))
    assert eventos["verificacao"]["eh_minuta"] is True
    assert eventos["verificacao"]["aviso"] == AVISO


def test_pergunta_simultanea_na_mesma_conversa_e_recusada(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM))
    sid = _sid(cliente)
    main._EM_ANDAMENTO.add(sid)
    try:
        eventos = _chat(cliente, sid)
    finally:
        main._EM_ANDAMENTO.discard(sid)
    assert [n for n, _ in eventos] == ["erro"] and "andamento" in eventos[0][1]["mensagem"]


def test_pergunta_vazia_ou_grande_demais(cliente):
    sid = _sid(cliente)
    assert cliente.post("/api/chat", json={"sessao_id": sid, "pergunta": ""}).status_code == 422
    assert cliente.post("/api/chat",
                        json={"sessao_id": sid, "pergunta": "x" * 4001}).status_code == 422


def test_validar_banco_com_mensagem_clara(tmp_path):
    with pytest.raises(RuntimeError, match="não encontrado"):
        main._validar_banco(str(tmp_path / "nao-existe.sqlite"))
    lixo = tmp_path / "lixo.sqlite"
    lixo.write_text("isto não é um banco", encoding="utf-8")
    with pytest.raises(RuntimeError, match="não é um banco SQLite"):
        main._validar_banco(str(lixo))
    vazio = tmp_path / "vazio.sqlite"
    sqlite3.connect(vazio).close()
    with pytest.raises(RuntimeError, match="faltam as tabelas"):
        main._validar_banco(str(vazio))


def test_documento_fora_da_conversa_403(cliente):
    sid = _sid(cliente)
    assert cliente.get(f"/api/documento/93?sessao_id={sid}").status_code == 403
    assert cliente.get("/api/documento/93?sessao_id=nao-e-um-id").status_code == 403


def test_documento_lido_na_conversa_200(cliente):
    from app.agente.sessao import obter_sessao
    from app.dados.ferramentas import obter_dossie

    sid = _sid(cliente)
    obter_sessao(sid).registrar_resultado("obter_dossie", obter_dossie(NUM))
    r = cliente.get(f"/api/documento/93?sessao_id={sid}")
    assert r.status_code == 200
    assert r.json()["id"] == 93 and r.json()["numero"] == NUM and r.json()["texto"]
    assert cliente.get(f"/api/documento/94?sessao_id={sid}").status_code == 403  # outro processo


def test_perguntas_recusadas_tambem_sao_registradas(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM))
    sid = _sid(cliente)
    main._EM_ANDAMENTO.add(sid)
    try:
        _chat(cliente, sid, "primeira")
    finally:
        main._EM_ANDAMENTO.discard(sid)
    assert _ultima_auditoria()["recusada"] == "em_andamento"
    monkeypatch.setattr(main, "custo_acumulado", lambda caminho=None: 999.0)
    _chat(cliente, sid, "segunda")
    linha = _ultima_auditoria()
    assert linha["recusada"] == "orcamento" and linha["pergunta"] == "segunda"


def test_id_de_sessao_grande_demais_422(cliente):
    r = cliente.post("/api/chat", json={"sessao_id": "x" * 65, "pergunta": "oi"})
    assert r.status_code == 422


def test_sql_marcado_apos_busca_conta_como_consulta(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake(
        {"tipo": "ferramenta", "nome": "buscar_processos", "args": {"parte": "Financeira"},
         "duracao_ms": 3.0, "resumo": "527 encontrado(s)"},
        {"tipo": "texto", "delta": "São 527 processos [SQL]."}, FIM))
    eventos = dict(_chat(cliente, _sid(cliente)))
    assert ("citacao", "ok") in {(s["tipo"], s["status"]) for s in eventos["verificacao"]["selos"]}


def test_turno_registrado_e_conversa_liberada_antes_do_fim(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM))
    sse, visto = main._sse, {}

    def espiao(evento, dados):
        if evento == "fim":  # o que o cliente já pode observar ao receber o fim
            visto["registrado"] = Path(main.AUDITORIA).exists()
            visto["livre"] = sid not in main._EM_ANDAMENTO
        return sse(evento, dados)

    monkeypatch.setattr(main, "_sse", espiao)
    sid = _sid(cliente)
    assert [n for n, _ in _chat(cliente, sid)][-1] == "fim"
    assert visto == {"registrado": True, "livre": True}
    assert "erro" not in [n for n, _ in _chat(cliente, sid)]  # a pergunta seguinte é aceita


def test_custo_da_sessao_no_fim_e_o_deste_turno(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM,
                                                 preparo=_com_doc_93))
    sse = main._sse

    def espiao(evento, dados):
        if evento == "verificacao":  # outra pergunta da mesma conversa soma custo neste intervalo
            main.obter_sessao(sid).custo_total += 1.0
        return sse(evento, dados)

    monkeypatch.setattr(main, "_sse", espiao)
    sid = _sid(cliente)
    fim = [d for n, d in _chat(cliente, sid) if n == "fim"][0]
    assert fim["custo_sessao"] == 0.001


def test_falha_na_verificacao_tambem_atualiza_o_turno_de_minuta(cliente, monkeypatch):
    monkeypatch.setattr(main, "responder", _fake({"tipo": "texto", "delta": "oi"}, FIM))

    def quebra(*a, **k):
        raise TypeError("boom")

    monkeypatch.setattr(main, "verificar", quebra)
    sid = _sid(cliente)
    main.obter_sessao(sid).ultimo_turno_minuta = True  # o turno anterior foi de minuta
    _chat(cliente, sid)
    assert main.obter_sessao(sid).ultimo_turno_minuta is False  # "oi" não é minuta redigida
