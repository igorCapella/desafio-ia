import json
import threading

import pytest

from app.agente import ciclo
from app.agente.sessao import Sessao

NUM = "0000001-15.2022.8.99.9012"


def _fake_stream(roteiro, capturadas=None):
    """roteiro: lista de 'turnos'; cada turno é a lista de eventos que o modelo emite."""
    turnos = iter(roteiro)

    async def stream_fn(mensagens, tools):
        if capturadas is not None:
            capturadas.append(mensagens)
        for ev in next(turnos):
            yield ev
    return stream_fn


def _chamada(nome, args, id_="c1"):
    return {"tipo": "tool_calls", "tool_calls": [
        {"id": id_, "type": "function",
         "function": {"name": nome, "arguments": json.dumps(args)}}]}


def _fim(finish="stop", custo=0.001, **extra):
    return [{"tipo": "uso", "uso": {"cost": custo}, **extra}, {"tipo": "fim", "finish": finish}]


async def _rodar(sessao, pergunta, roteiro, capturadas=None):
    return [e async for e in ciclo.responder(sessao, pergunta,
                                             stream_fn=_fake_stream(roteiro, capturadas))]


def _tool_msgs(sessao):
    return [m for m in sessao.historico if m["role"] == "tool"]


@pytest.mark.anyio
async def test_uma_ferramenta_depois_texto():
    roteiro = [[_chamada("obter_dossie", {"numero": NUM}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "Processo julgado."}, *_fim()]]
    s = Sessao()
    eventos = await _rodar(s, "Já foi julgado?", roteiro)
    tipos = [e["tipo"] for e in eventos]
    assert "ferramenta" in tipos and "texto" in tipos and tipos[-1] == "fim"
    assert s.processo_em_foco == NUM
    ficha = next(e for e in eventos if e["tipo"] == "processo")["ficha"]
    assert ficha["numero"] == NUM and ficha["partes"] and ficha["movimentacoes"]
    assert "texto" not in ficha["documentos"][0]
    assert 86 in s.docs_vistos and NUM in s.processos_consultados


@pytest.mark.anyio
async def test_limite_de_passos_responde_e_lista_consultas():
    turno = [_chamada("consultar_sql", {"sql": "select 1"}), *_fim("tool_calls", custo=0.0)]
    eventos = await _rodar(Sessao(), "loop", [turno] * 20)
    texto = "".join(e["delta"] for e in eventos if e["tipo"] == "texto")
    assert "limite" in texto and "consultar_sql" in texto
    assert eventos[-1]["tipo"] == "fim"
    assert sum(e["tipo"] == "ferramenta" for e in eventos) == ciclo.MAX_PASSOS


@pytest.mark.anyio
async def test_filtra_argumentos_nao_declarados():
    roteiro = [[_chamada("obter_dossie", {"numero": NUM, "conn": "x"}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    eventos = await _rodar(Sessao(), "Resuma o processo " + NUM, roteiro)
    ferramenta = next(e for e in eventos if e["tipo"] == "ferramenta")
    assert ferramenta["args"] == {"numero": NUM}
    assert not ferramenta["resumo"].startswith("erro")


@pytest.mark.anyio
async def test_modelo_nao_se_autoautoriza_a_buscar_cpf():
    args = {"cpf_cnpj": "999.550.862-21", "cpfs_do_usuario": ["99955086221"]}
    roteiro = [[_chamada("buscar_processos", args), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    eventos = await _rodar(Sessao(), "Quais processos dessa pessoa?", roteiro)
    ferramenta = next(e for e in eventos if e["tipo"] == "ferramenta")
    assert ferramenta["resumo"].startswith("erro") and "digitado" in ferramenta["resumo"]


@pytest.mark.anyio
async def test_cpf_digitado_pelo_usuario_autoriza_a_busca():
    roteiro = [[_chamada("buscar_processos", {"cpf_cnpj": "99955086221"}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    eventos = await _rodar(Sessao(), "Processos do CPF 999.550.862-21?", roteiro)
    ferramenta = next(e for e in eventos if e["tipo"] == "ferramenta")
    assert ferramenta["resumo"] == "1 encontrado(s)"


@pytest.mark.anyio
async def test_argumento_invalido_e_numero_vazio_viram_erro_em_portugues():
    chamadas = [
        {"id": "a", "type": "function",
         "function": {"name": "obter_dossie", "arguments": json.dumps({"numero": ["x"]})}},
        {"id": "b", "type": "function",
         "function": {"name": "obter_dossie", "arguments": json.dumps({"numero": ""})}},
        {"id": "c", "type": "function", "function": {"name": "inexistente", "arguments": "{}"}},
    ]
    roteiro = [[{"tipo": "tool_calls", "tool_calls": chamadas}, *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "Informe o número do processo."}, *_fim()]]
    eventos = await _rodar(Sessao(), "resuma o processo", roteiro)
    resumos = [e["resumo"] for e in eventos if e["tipo"] == "ferramenta"]
    assert resumos[0] == "erro: O parâmetro 'numero' deve ser texto."
    assert resumos[1].startswith("erro: O número deve ter 20 dígitos")
    assert resumos[2] == "erro: Ferramenta desconhecida: inexistente."


@pytest.mark.anyio
async def test_ferramentas_rodam_fora_do_event_loop(monkeypatch):
    na_thread_principal = []

    def sql_falso(sql):
        na_thread_principal.append(threading.current_thread() is threading.main_thread())
        return {"sql": sql, "colunas": ["x"], "linhas": [[1]], "truncado": False}

    monkeypatch.setitem(ciclo.IMPL, "consultar_sql", sql_falso)
    roteiro = [[_chamada("consultar_sql", {"sql": "select 1"}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "1"}, *_fim()]]
    await _rodar(Sessao(), "conta", roteiro)
    assert na_thread_principal == [False]


@pytest.mark.anyio
async def test_uso_acumula_tokens_modelo_e_provedor():
    roteiro = [[{"tipo": "texto", "delta": "oi"},
                {"tipo": "uso", "uso": {"cost": 0.002, "prompt_tokens": 10, "completion_tokens": 5,
                                        "completion_tokens_details": {"reasoning_tokens": 3}},
                 "modelo": "deepseek/deepseek-v4.1-flash", "provedor": "Makora"},
                {"tipo": "fim", "finish": "stop"}]]
    s = Sessao()
    eventos = await _rodar(s, "oi", roteiro)
    uso = eventos[-1]["uso"]
    assert (uso["prompt"], uso["completion"], uso["raciocinio"]) == (10, 5, 3)
    assert uso["modelo"] == "deepseek/deepseek-v4.1-flash" and uso["provedor"] == "Makora"
    assert uso["latencia_ms"] >= 0 and s.custo_total == pytest.approx(0.002)


@pytest.mark.anyio
async def test_status_informa_as_fases():
    roteiro = [[_chamada("consultar_sql", {"sql": "select 1"}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    eventos = await _rodar(Sessao(), "x", roteiro)
    fases = [e["fase"] for e in eventos if e["tipo"] == "status"]
    assert fases == ["pensando", "consultando", "pensando", "escrevendo"]


@pytest.mark.anyio
async def test_historico_enviado_ao_modelo_sem_chaves_internas():
    capturadas = []
    roteiro = [[_chamada("obter_dossie", {"numero": NUM}), *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    await _rodar(Sessao(), "resuma " + NUM, roteiro, capturadas)
    segunda = capturadas[1]
    assert all(not k.startswith("_") for m in segunda for k in m)
    assert segunda[0]["role"] == "system" and "Processo em foco: nenhum" in segunda[1]["content"]


@pytest.mark.anyio
async def test_dois_dossies_no_mesmo_turno_nao_se_compactam():
    outro = "0000001-14.2023.8.99.9001"
    chamadas = [{"id": i, "type": "function",
                 "function": {"name": "obter_dossie", "arguments": json.dumps({"numero": n})}}
                for i, n in (("a", NUM), ("b", outro))]
    roteiro = [[{"tipo": "tool_calls", "tool_calls": chamadas}, *_fim("tool_calls")],
               [{"tipo": "texto", "delta": "comparação"}, *_fim()]]
    s = Sessao()
    await _rodar(s, f"compare {NUM} e {outro}", roteiro)
    assert all("omitido" not in m["content"] for m in _tool_msgs(s))
    assert s.processo_em_foco == outro
    # No turno seguinte, ao trocar o foco para um terceiro processo, os dois antigos saem.
    terceiro = "0000001-63.2025.8.99.9059"
    roteiro2 = [[_chamada("obter_dossie", {"numero": terceiro}), *_fim("tool_calls")],
                [{"tipo": "texto", "delta": "ok"}, *_fim()]]
    await _rodar(s, "e o " + terceiro + "?", roteiro2)
    compactados = [m["_numero"] for m in _tool_msgs(s) if "omitido" in m["content"]]
    assert sorted(compactados) == sorted([NUM, outro])


@pytest.mark.anyio
async def test_falha_do_modelo_vira_erro():
    async def quebra(mensagens, tools):
        raise RuntimeError("HTTP 503: indisponível")
        yield  # pragma: no cover  (faz desta função um gerador assíncrono)

    eventos = [e async for e in ciclo.responder(Sessao(), "oi", stream_fn=quebra)]
    assert eventos[-1]["tipo"] == "erro"
    assert "Falha ao consultar o modelo" in eventos[-1]["mensagem"]


def test_prompt_cobre_os_itens_da_spec():
    p = ciclo.carregar_prompt()
    for trecho in ("[Doc", "[Mov", "[Cadastro]", "[SQL]", "Fontes consultadas", "[verificar]",
                   "PROPOSTA DE TEXTO GERADA POR IA", "colchetes", "Processo em foco",
                   "v_processo", "v_partes", "v_documentos", "v_movimentacoes", "v_magistrados",
                   "v_unidades", "normalizar"):
        assert trecho in p, trecho


@pytest.fixture
def anyio_backend():
    return "asyncio"
