from app.verificacao.minuta import AVISO, eh_minuta, verificar_minuta

MINUTA = (f"**{AVISO}**\n\n## I – RELATÓRIO\nTrata-se de ação... "
          "[Doc 86 – Petição Inicial, 24/10/2022]\n\n"
          "## II – FUNDAMENTAÇÃO\nA prova dos autos...\n\n## III – DISPOSITIVO\n"
          "Ante o exposto, [JULGO PROCEDENTE / IMPROCEDENTE] o pedido.\n\n[Local e data]\n"
          "Juiz(a) de Direito")


def _alertas(selos):
    return [s["mensagem"] for s in selos if s["status"] == "alerta"]


def test_deteccao_por_pedido_ou_aviso():
    assert eh_minuta("...", "Elabore uma minuta de sentença para o processo X")
    assert eh_minuta(MINUTA, "e agora?")
    assert not eh_minuta("A sentença julgou improcedente.", "Qual foi a sentença?")


def test_minuta_correta_sem_alertas():
    selos = verificar_minuta(MINUTA, magistrado="Daiane Duarte Zanella", n_documentos=8,
                             ja_julgado=False)
    assert _alertas(selos) == []


def test_decide_merito_alerta():
    r = MINUTA.replace("[JULGO PROCEDENTE / IMPROCEDENTE]", "JULGO PROCEDENTE")
    assert any("decisão de mérito" in m for m in _alertas(verificar_minuta(r)))


def test_sem_aviso_alerta():
    assert any("aviso" in m for m in _alertas(verificar_minuta(MINUTA.replace(AVISO, ""))))


def test_assinada_pelo_magistrado_alerta():
    r = MINUTA.replace("Juiz(a) de Direito", "Daiane Duarte Zanella\nJuíza de Direito")
    selos = verificar_minuta(r, magistrado="Daiane Duarte Zanella")
    assert any("assinatura" in m for m in _alertas(selos))


def test_minuta_de_processo_sem_documentos_alerta():
    assert any("sem documentos" in m for m in _alertas(verificar_minuta(MINUTA, n_documentos=0)))


def test_recusa_explicada_sem_documentos_nao_alerta():
    r = (f"{AVISO}\n\nO processo não tem documentos no banco; sem elementos dos autos, "
         "não redijo a minuta.")
    assert _alertas(verificar_minuta(r, n_documentos=0)) == []


def test_processo_julgado_sem_aviso_alerta_e_com_aviso_nao():
    selos = verificar_minuta(MINUTA, ja_julgado=True, sentencas=[93])
    assert any("sentença" in m for m in _alertas(selos))
    avisada = MINUTA.replace("## I – RELATÓRIO", "Atenção: este processo já foi julgado "
                             "[Doc 93 – Sentença, 26/08/2024].\n\n## I – RELATÓRIO")
    assert _alertas(verificar_minuta(avisada, ja_julgado=True, sentencas=[93])) == []

def test_pergunta_sobre_a_sentenca_existente_nao_e_minuta():
    for p in ("Faça um resumo da sentença", "Escreva o que a sentença decidiu",
              "Elabore um resumo da sentença", "Qual foi a sentença?"):
        assert not eh_minuta("A sentença julgou improcedente.", p), p
    for p in ("Redija a sentença", "Escreva uma nova sentença", "Quero uma minuta"):
        assert eh_minuta("...", p), p


def test_dispositivo_citado_entre_aspas_nao_alerta():
    r = MINUTA.replace("Trata-se de ação...",
                       'A sentença anterior [Doc 93] disse: "julgo improcedente o pedido".')
    assert _alertas(verificar_minuta(r)) == []


def test_resposta_sem_minuta_redigida_nao_cobra_aviso():
    assert _alertas(verificar_minuta("Antes de redigir, confirme: o processo já foi julgado?")) == []

