import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main

ESTATICOS = Path("app/web/static")


def test_vendors_presentes():
    assert (ESTATICOS / "vendor/marked.umd.js").stat().st_size > 1000
    assert (ESTATICOS / "vendor/purify.min.js").stat().st_size > 1000


def test_index_usa_so_arquivos_locais():
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    for arquivo in ("estilo.css", "vendor/marked.umd.js", "vendor/purify.min.js", "nucleo.js", "app.js"):
        assert arquivo in html, arquivo
    assert not re.search(r'(src|href)\s*=\s*["\'](https?:)?//', html)  # nada de CDN em tempo de execução


def test_innerhtml_so_com_conteudo_sanitizado():
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    assert "marked.parse" in js and "DOMPurify.sanitize" in js
    for linha in js.splitlines():
        m = re.search(r"\.innerHTML\s*(\+?=)(?!=)", linha)
        if m:
            vazio = re.search(r"\.innerHTML\s*=\s*(\"\"|''|``)\s*;?\s*$", linha)
            assert m.group(1) == "=" and ("DOMPurify.sanitize(" in linha or vazio), linha


def test_pagina_servida_pela_api(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "AUDITORIA", str(tmp_path / "aud.jsonl"))
    with TestClient(main.app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "app.js" in r.text
