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
