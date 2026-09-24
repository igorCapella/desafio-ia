from app.verificacao.citacoes import verificar_citacoes

MOVS = {("2024-09-30", "Trânsito em Julgado"), ("2024-11-11", "Arquivamento Definitivo")}


def _status(selos):
    return {s["status"] for s in selos}


def test_doc_valido():
    selos = verificar_citacoes("Conforme [Doc 93 – Sentença], improcedente.",
                               docs_vistos={93: "texto"}, movs_vistas=set(), houve_sql=False)
    assert _status(selos) == {"ok"}


def test_doc_inexistente_alerta():
    selos = verificar_citacoes("Segundo [Doc 999], ...",
                               docs_vistos={93: "texto"}, movs_vistas=set(), houve_sql=False)
    assert any(s["status"] == "alerta" and "999" in " ".join(s["trechos"]) for s in selos)


def test_sql_sem_consulta_alerta():
    selos = verificar_citacoes("O total é 190 [SQL].",
                               docs_vistos={}, movs_vistas=set(), houve_sql=False)
    assert _status(selos) == {"alerta"}


def test_sql_com_consulta_ok():
    selos = verificar_citacoes("O total é 190 [SQL].",
                               docs_vistos={}, movs_vistas=set(), houve_sql=True)
    assert _status(selos) == {"ok"}


def test_mov_confere_com_data_brasileira_ou_iso():
    r = ("Transitou em julgado [Mov 30/09/2024 – Trânsito em Julgado] e foi arquivado "
         "[Mov 2024-11-11 – Arquivamento Definitivo].")
    selos = verificar_citacoes(r, docs_vistos={}, movs_vistas=MOVS, houve_sql=False)
    assert _status(selos) == {"ok"}


def test_mov_inexistente_ou_generica_alerta():
    r = "Houve audiência [Mov 01/02/2023 – Audiência Realizada]; ver também [Mov ...]."
    selos = verificar_citacoes(r, docs_vistos={}, movs_vistas=MOVS, houve_sql=False)
    alerta = next(s for s in selos if s["status"] == "alerta")
    assert len(alerta["trechos"]) == 2

def test_varios_documentos_no_mesmo_marcador():
    r = "Ver [Doc 86, 90], [Docs 86 e 91] e (Doc 92); também [Doc 86, 24/10/2022]."
    selos = verificar_citacoes(r, docs_vistos={86: "", 90: "", 91: ""}, movs_vistas=set(),
                               houve_sql=False)
    alerta = next(s for s in selos if s["status"] == "alerta")
    assert alerta["trechos"] == ["Doc 92"]


def test_mov_descricao_sem_acento_confere():
    selos = verificar_citacoes("[Mov 30/09/2024 – Transito em julgado]", docs_vistos={},
                               movs_vistas=MOVS, houve_sql=False)
    assert _status(selos) == {"ok"}

