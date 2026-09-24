import json

from app.auditoria import custo_acumulado, registrar


def test_registra_e_soma(tmp_path):
    p = tmp_path / "aud.jsonl"
    registrar({"pergunta": "oi", "custo": 0.002}, caminho=str(p))
    registrar({"pergunta": "oi2", "custo": 0.003}, caminho=str(p))
    linhas = p.read_text().strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[0])["pergunta"] == "oi"
    assert abs(custo_acumulado(str(p)) - 0.005) < 1e-9


def test_mascara_cpf_e_remove_chave_em_qualquer_campo(tmp_path):
    p = tmp_path / "aud.jsonl"
    registrar({"pergunta": "Processos do CPF 999.550.862-21?",
               "ferramentas": [{"nome": "buscar_processos", "args": {"cpf_cnpj": "99955086221"}}],
               "erros": ["Authorization: Bearer sk-or-v1-0123456789abcdef"], "custo": 0.00123456789},
              caminho=str(p))
    texto = p.read_text(encoding="utf-8")
    assert "***.550.862-**" in texto
    assert "999.550.862-21" not in texto and "99955086221" not in texto
    assert "sk-or-v1" not in texto
    assert json.loads(texto)["custo"] == 0.00123456789  # número intacto (só texto é limpo)


def test_linha_corrompida_nao_derruba_o_custo(tmp_path):
    p = tmp_path / "aud.jsonl"
    registrar({"custo": 0.002}, caminho=str(p))
    with p.open("a", encoding="utf-8") as f:
        f.write('{"custo": 0.0\n')  # gravação interrompida
    registrar({"custo": 0.003}, caminho=str(p))
    assert abs(custo_acumulado(str(p)) - 0.005) < 1e-9

def test_chaves_de_dict_objetos_e_cpf_com_espacos_tambem_sao_limpos(tmp_path):
    class Objeto:
        def __str__(self):
            return "CPF 999.550.862-21"

    p = tmp_path / "aud.jsonl"
    registrar({"args": {"999.550.862-21": "x"}, "extra": Objeto(), "espacos": "999 550 862 21"},
              caminho=str(p))
    texto = p.read_text(encoding="utf-8")
    assert "550.862-21" not in texto and "550 862 21" not in texto and "999.550" not in texto


def test_remove_bearer_e_o_valor_real_de_segredos(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTRO_TOKEN", "segredo-muito-secreto-123")
    p = tmp_path / "aud.jsonl"
    registrar({"erros": ["Authorization: Bearer abc.def.ghi",
                         "falhou com token=segredo-muito-secreto-123"]}, caminho=str(p))
    texto = p.read_text(encoding="utf-8")
    assert "abc.def.ghi" not in texto and "segredo-muito-secreto-123" not in texto
    assert texto.count("[chave removida]") == 2
