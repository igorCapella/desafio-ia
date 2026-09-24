from app.dados.alertas import alertas_do_processo


def _id(conn, numero):
    return conn.execute("select id from processo where numero=?", (numero,)).fetchone()[0]


def _junta(conn, numero):
    return " ".join(alertas_do_processo(conn, _id(conn, numero)))


def test_sem_documentos(conn):
    txt = _junta(conn, "0000001-14.2023.8.99.9001")
    assert "documento" in txt.lower()


def test_sem_magistrado(conn):
    txt = _junta(conn, "0000001-63.2025.8.99.9059")
    assert "magistrado" in txt.lower()
    assert "Daiane Duarte Zanella" in txt  # magistrada da unidade, rotulada sem vínculo
    assert "sem vínculo" in txt.lower()


def test_tipo_diverge_do_polo(conn):
    txt = _junta(conn, "0000001-14.2023.8.99.9001")
    assert "polo" in txt.lower()


def test_julgado_sem_data(conn):
    txt = _junta(conn, "0000003-78.2023.8.99.9002")
    assert "sentença" in txt.lower() and "sem data" in txt.lower()


def test_valor_zero(conn):
    txt = _junta(conn, "0000001-38.2024.8.99.9014")
    assert "valor da causa" in txt.lower()


def test_assinatura_divergente(conn):
    txt = _junta(conn, "0000001-46.2021.8.99.9013")
    assert "assinatura" in txt.lower()


def test_acordo_nao_alerta_assinatura(conn):
    # processo com Petição de Acordo (duas assinaturas) não gera alerta de assinatura
    txt = _junta(conn, "0000001-57.2023.8.99.9019")
    assert "assinatura" not in txt.lower()


def test_audiencia_data_divergente(conn):
    txt = _junta(conn, "0000001-57.2023.8.99.9019")
    assert "audiência" in txt.lower()


def test_processo_sem_alertas(conn):
    assert alertas_do_processo(conn, _id(conn, "0000001-15.2022.8.99.9012")) == []
