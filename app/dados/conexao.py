import re
import sqlite3
import threading
import unicodedata

from app.config import get_settings
from app.dados.visoes import criar_visoes

SHA256_ESPERADO = "8a90b47cdc3b07bcb395ffe0e81c3d56dd33946fa047dec7dc86499767690c43"

VISOES = ("v_processo", "v_partes", "v_documentos", "v_movimentacoes",
          "v_magistrados", "v_unidades")

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


def _registrar_funcoes(c: sqlite3.Connection) -> None:
    c.create_function("normalizar", 1, py_normalizar, deterministic=True)
    c.create_function("advogado_de", 1, py_advogado_de, deterministic=True)
    c.create_function("oab_de", 1, py_oab_de, deterministic=True)
    c.create_function("mascarar_cpf", 1, py_mascarar_cpf, deterministic=True)


def abrir_conexao(db_path: str | None = None) -> sqlite3.Connection:
    caminho = db_path or get_settings().db_path
    c = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    _registrar_funcoes(c)
    criar_visoes(c, mascarar=get_settings().mascarar_cpf)
    return c


# --- Base de consulta do modelo ---------------------------------------------
# O SQL escrito pelo modelo não roda no banco original: roda numa cópia em
# memória que só contém as visões materializadas (CPF já mascarado). Tabela base
# não existe ali, então nenhum truque de SQL (CTE com nome de visão, subconsulta)
# alcança o dado cru. A conexão ainda é somente leitura, com query_only, ATTACH
# desligado e authorizer que só permite SELECT/READ/FUNCTION/RECURSIVE.

_URI_CONSULTA = "file:/consulta_modelo?vfs=memdb"
_ACOES_CONSULTA = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                   sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
_guardia: sqlite3.Connection | None = None  # mantém a base em memória viva
_trava = threading.Lock()


def _preparar_base_consulta() -> None:
    global _guardia
    with _trava:
        if _guardia is not None:
            return
        guardia = sqlite3.connect(_URI_CONSULTA, uri=True, check_same_thread=False)
        origem = abrir_conexao()
        try:
            origem.execute(f"attach database '{_URI_CONSULTA}' as consulta")
            for v in VISOES:
                origem.execute(f"create table consulta.{v} as select * from temp.{v}")
            origem.execute("detach database consulta")
        finally:
            origem.close()
        _guardia = guardia


def _autorizar_consulta(acao, *_):
    return sqlite3.SQLITE_OK if acao in _ACOES_CONSULTA else sqlite3.SQLITE_DENY


def abrir_conexao_consulta() -> sqlite3.Connection:
    _preparar_base_consulta()
    c = sqlite3.connect(f"{_URI_CONSULTA}&mode=ro", uri=True)
    _registrar_funcoes(c)
    c.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    c.execute("pragma query_only = on")
    c.set_authorizer(_autorizar_consulta)
    return c
