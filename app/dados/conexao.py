import re
import sqlite3
import unicodedata

from app.config import get_settings

SHA256_ESPERADO = "8a90b47cdc3b07bcb395ffe0e81c3d56dd33946fa047dec7dc86499767690c43"

_RX_OAB = re.compile(r"OAB/[A-Z]{2}\s+[\d.]+")
_RX_ADV = re.compile(r"^(Dra?\.\s+.+?)\s+—\s+OAB/[A-Z]{2}\s+[\d.]+")
_RX_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_RX_CPF = re.compile(r"\d{3}\.?(\d{3})\.?(\d{3})-?\d{2}")


def py_normalizar(s: str | None) -> str | None:
    if s is None:
        return None
    sem_acento = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def py_oab_de(s: str | None) -> str | None:
    m = _RX_OAB.search(s or "")
    return m.group(0) if m else None


def py_advogado_de(s: str | None) -> str | None:
    m = _RX_ADV.match((s or "").strip())
    return m.group(1) if m else None


def py_mascarar_cpf(s: str | None) -> str | None:
    # Fail-closed: só CNPJ reconhecido passa intacto (não é dado pessoal na LGPD);
    # CPF (formatado ou só dígitos) vira ***.xxx.xxx-**; qualquer outro formato
    # tem todos os dígitos mascarados.
    if not s:
        return s
    v = s.strip()
    if _RX_CNPJ.fullmatch(v):
        return v
    m = _RX_CPF.fullmatch(v)
    if m:
        return f"***.{m.group(1)}.{m.group(2)}-**"
    return re.sub(r"\d", "*", v)


def verificar_integridade(db_path: str) -> bool:
    import hashlib
    with open(db_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest() == SHA256_ESPERADO


def abrir_conexao(db_path: str | None = None) -> sqlite3.Connection:
    caminho = db_path or get_settings().db_path
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    c.create_function("normalizar", 1, py_normalizar, deterministic=True)
    c.create_function("advogado_de", 1, py_advogado_de, deterministic=True)
    c.create_function("oab_de", 1, py_oab_de, deterministic=True)
    c.create_function("mascarar_cpf", 1, py_mascarar_cpf, deterministic=True)
    try:
        from app.dados.visoes import criar_visoes
        criar_visoes(c, mascarar=get_settings().mascarar_cpf)
    except ImportError:
        pass
    return c
