from app.verificacao.processo import verificar_processo_foco

FOCO = "0000001-15.2022.8.99.9012"


def test_foco_e_consultados_ok():
    r = f"O processo {FOCO} e o 0000002-97.2022.8.99.9012 ..."
    selos = verificar_processo_foco(r, FOCO, {"0000002-97.2022.8.99.9012"})
    assert [s["status"] for s in selos] == ["ok"]


def test_outro_processo_alerta():
    selos = verificar_processo_foco("Veja o 0000009-99.2021.8.99.9001.", FOCO, set())
    assert selos[0]["status"] == "alerta"
    assert selos[0]["trechos"] == ["0000009-99.2021.8.99.9001"]


def test_sem_numero_nao_gera_selo():
    assert verificar_processo_foco("Nada aqui.", FOCO, set()) == []
