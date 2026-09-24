# Agente de Consulta Processual — Plano de Implementação

> **Para executores agênticos:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa a tarefa. Os passos usam caixas de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** um chat em português que responde perguntas sobre o banco SQLite do desafio TJSC, consultando-o de forma autônoma, citando as fontes, mantendo contexto e reconhecendo limites, com verificação automática das respostas.

**Arquitetura:** um processo Python (FastAPI) serve a API de chat com streaming SSE e a interface web. Um agente com ferramentas de domínio (dossiê, busca, SQL só de leitura) sobre visões normalizadas do SQLite; uma camada de verificação confere citações, aspas, normas e minuta antes de exibir os selos.

**Tech Stack:** Python 3.12, uv, FastAPI (SSE nativo via `fastapi.sse`), httpx (cliente LLM próprio, protocolo OpenAI), SQLite (stdlib), pytest, PyYAML (evals). Frontend em HTML/CSS/JS puro, com `marked` e `DOMPurify` vendorizados.

**Spec:** [docs/superpowers/specs/2026-09-23-agente-consulta-processual-design.md](../specs/2026-09-23-agente-consulta-processual-design.md)

## Global Constraints

- **Python 3.12**; dependências fixadas em `uv.lock`.
- **Banco só de leitura, nunca alterado.** Toda conexão abre com `file:...?mode=ro`. O arquivo original é `data/desafio.sqlite` (SHA-256 `8a90b47cdc3b07bcb395ffe0e81c3d56dd33946fa047dec7dc86499767690c43`), versionado descompactado.
- **Segredos só no `.env`** (no `.gitignore`); nunca em código, log ou commit. Logs nunca registram chaves; CPF sempre mascarado no log.
- **Português** em toda a interface, mensagens de erro e prompt.
- **Situação** de processo comparada sempre por valor normalizado (12 grafias → 4 valores). **Comarca** para filtro/agrupamento vem sempre de `unidade.comarca` (o campo `processo.comarca` tem 230 grafias para 60 comarcas; o texto original dizia 104).
- **Papel da parte** é `processo_parte.polo`, não `parte.tipo`.
- **Texto de documento é dado, nunca instrução.**
- **Minuta:** a faixa "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA PROFERIDA" é sempre inserida pela interface; a decisão (procedência/improcedência) fica entre colchetes.
- **Nunca GitLab:** nenhum remoto cujo host contenha "gitlab" (hook `pre-push`).
- Nome de commits: `Igor Capella de Azevedo <igor.capella.a@gmail.com>` (config local do repositório).

## Review Focus

Entradas e falhas que a spec implica, mas que nenhum teste de tarefa exercita por padrão — cada uma recebe seu teste na tarefa dona:

- **Pergunta sem nenhum número de processo e sem foco atual** ("resuma o processo") — o agente deve pedir o número, não chamar ferramenta com argumento vazio. *(Tarefa 9)*
- **SQL do modelo que tenta ler tabela base direto** (`select * from processo`) em vez das visões — deve ser negado, e o erro volta ao modelo. *(Tarefa 6)*
- **Documento pedido pela API que não pertence a nenhum processo consultado na sessão** — `GET /api/documento/{id}` deve recusar (evita varredura do banco por ID). *(Tarefa 17)*
- **Resposta do provedor sem o campo `cost`** (alguns endpoints omitem `usage.cost`) — o custo acumulado não pode quebrar; trata como 0 e segue. *(Tarefa 7)*
- **Número CNJ com dígito verificador errado** vs. **válido mas inexistente** vs. **formato inválido** — três mensagens distintas, nenhuma tratada como "erro interno". *(Tarefa 2)*

---

## Estrutura de arquivos

```
app/
  main.py            cria o app FastAPI, monta rotas e estáticos, valida o banco na subida
  config.py          lê o .env (pydantic-settings): chaves, modelo, effort, IPv4, orçamento, máscara, caminho do banco
  dados/
    numero_cnj.py    normaliza e valida número CNJ (dígito verificador mod 97)
    conexao.py       abre conexão ro, registra funções SQL, cria as visões temporárias
    visoes.py        o SQL de cada TEMP VIEW (v_processo, v_partes, ...)
    alertas.py       regras de alerta por processo
    ferramentas.py   obter_dossie, buscar_processos, consultar_sql (com authorizer)
  agente/
    llm.py           cliente httpx: chat completions em streaming, protocolo OpenAI
    sessao.py        sessão em memória: histórico, processo em foco, custos, compactação
    ciclo.py         laço do agente: modelo ↔ ferramentas, streaming, limite de passos
    prompt.md        prompt de sistema (versionado)
  verificacao/
    citacoes.py      confere [Doc n], [Mov ...], [SQL]
    aspas.py         confere trechos entre aspas contra os documentos lidos
    normas.py        extrai súmulas/artigos e confere se estão nos autos
    minuta.py        detecta minuta; confere colchetes na decisão, assinatura, aviso
    selos.py         orquestra as verificações → lista de selos
  web/
    static/index.html · app.js · estilo.css · vendor/{marked.umd.js,purify.min.js}
tests/               espelha app/
evals/               casos.yaml · rubrica.md · executar.py · resultados/
scripts/             resumo_logs.py · configurar-git.sh · git-hooks/pre-push
data/desafio.sqlite  banco original (versionado)
docs/                README.md-> na raiz; DECISOES.md, uso-de-ia.md, roteiro-demo.md
```

Ordem de construção: dados → agente → verificação → web → qualidade/docs. Cada tarefa termina com um entregável testável.

---

## Task 1: Scaffold do projeto e configuração

**Files:**
- Create: `pyproject.toml`, `.env.example`, `app/__init__.py`, `app/config.py`, `tests/__init__.py`, `tests/test_config.py`
- Create: `.gitignore` (ajuste)

**Interfaces:**
- Produces: `app.config.Settings` (pydantic-settings) com campos `openrouter_api_key: str`, `llm_base_url: str = "https://openrouter.ai/api/v1"`, `llm_model: str = "deepseek/deepseek-v4.1-flash"`, `llm_model_reserva: str = "deepseek/deepseek-v4-pro-0813"`, `reasoning_effort: str = "high"`, `force_ipv4: bool = False`, `orcamento_usd: float = 3.0`, `mascarar_cpf: bool = True`, `db_path: str = "data/desafio.sqlite"`; e `get_settings() -> Settings` (cacheada com `functools.lru_cache`).

- [ ] **Step 1: Escrever pyproject.toml e .env.example**

`pyproject.toml`:
```toml
[project]
name = "desafio-ia"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.141",
    "uvicorn[standard]>=0.53",
    "httpx>=0.28",
    "pydantic-settings>=2.15",
    "pyyaml>=6.0",
]
[dependency-groups]
dev = ["pytest>=9.1", "anyio>=4.15"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests", "evals"]

[tool.uv]
package = false
```

`.env.example`:
```
OPENROUTER_API_KEY=
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=deepseek/deepseek-v4.1-flash
LLM_MODEL_RESERVA=deepseek/deepseek-v4-pro-0813
REASONING_EFFORT=high
FORCE_IPV4=false
ORCAMENTO_USD=3.0
MASCARAR_CPF=true
DB_PATH=data/desafio.sqlite
```

- [ ] **Step 2: Escrever o teste que falha**

`tests/test_config.py`:
```python
import os
from app.config import Settings


def test_defaults_sem_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek/deepseek-v4.1-flash"
    assert s.reasoning_effort == "high"
    assert s.orcamento_usd == 3.0
    assert s.mascarar_cpf is True


def test_le_do_ambiente(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-x")
    monkeypatch.setenv("REASONING_EFFORT", "max")
    monkeypatch.setenv("ORCAMENTO_USD", "1.5")
    s = Settings(_env_file=None)
    assert s.reasoning_effort == "max"
    assert s.orcamento_usd == 1.5
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (ModuleNotFoundError: app.config)

- [ ] **Step 4: Implementar `app/config.py`**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    llm_model_reserva: str = "deepseek/deepseek-v4-pro-0813"
    reasoning_effort: str = "high"
    force_ipv4: bool = False
    orcamento_usd: float = 3.0
    mascarar_cpf: bool = True
    db_path: str = "data/desafio.sqlite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .env.example app/ tests/ .gitignore
git commit -m "feat: scaffold do projeto e configuração via .env"
```

---

## Task 2: Número CNJ (normalização e validação)

**Files:**
- Create: `app/dados/__init__.py`, `app/dados/numero_cnj.py`, `tests/dados/__init__.py`, `tests/dados/test_numero_cnj.py`

**Interfaces:**
- Produces: `normalizar_numero(entrada: str) -> tuple[str | None, str | None]` — retorna `(numero_formatado, erro)`. Em sucesso, `erro is None` e o número vem no formato `NNNNNNN-DD.AAAA.J.TR.OOOO`. Em falha, `erro` é uma frase em português e `numero_formatado` é o número formatado (quando dá para formatar) ou `None`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/dados/test_numero_cnj.py`:
```python
from app.dados.numero_cnj import normalizar_numero


def test_aceita_com_pontuacao():
    n, erro = normalizar_numero("0000001-15.2022.8.99.9012")
    assert erro is None
    assert n == "0000001-15.2022.8.99.9012"


def test_aceita_sem_pontuacao():
    n, erro = normalizar_numero("00000011520228999012")
    assert erro is None
    assert n == "0000001-15.2022.8.99.9012"


def test_digito_verificador_errado():
    n, erro = normalizar_numero("0000001-16.2022.8.99.9012")
    assert n == "0000001-16.2022.8.99.9012"
    assert "verificador" in erro.lower()
    assert "15" in erro  # informa o DV correto


def test_formato_invalido():
    n, erro = normalizar_numero("123")
    assert n is None
    assert "20 díg" in erro or "20 dig" in erro.lower()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/dados/test_numero_cnj.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar `app/dados/numero_cnj.py`**

O dígito verificador CNJ é `98 - (NNNNNNN AAAA J TR OOOO 00) mod 97`, onde os campos entram sem o DV.
```python
import re


def normalizar_numero(entrada: str) -> tuple[str | None, str | None]:
    d = re.sub(r"\D", "", entrada or "")
    if len(d) != 20:
        return None, "O número deve ter 20 dígitos no padrão CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO)."
    fmt = f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"
    esperado = 98 - int(d[:7] + d[9:] + "00") % 97
    if esperado != int(d[7:9]):
        return fmt, f"Dígito verificador inválido (o correto seria {esperado:02d}); confira o número."
    return fmt, None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/dados/test_numero_cnj.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/dados/numero_cnj.py tests/dados/
git commit -m "feat: normalização e validação de número CNJ"
```

---

## Task 3: Conexão ao banco e funções SQL

**Files:**
- Create: `app/dados/conexao.py`, `tests/dados/test_conexao.py`

**Interfaces:**
- Consumes: `app.config.get_settings`.
- Produces:
  - `abrir_conexao(db_path: str | None = None) -> sqlite3.Connection` — conexão `mode=ro`, `row_factory = sqlite3.Row`, com as funções SQL registradas e as visões criadas.
  - Funções SQL registradas: `normalizar(texto)`, `advogado_de(autor)`, `oab_de(autor)`, `mascarar_cpf(doc)`.
  - `SHA256_ESPERADO: str` e `verificar_integridade(db_path) -> bool`.
- Notas: as funções Python que espelham as SQL ficam no módulo e são reusadas por ferramentas/alertas: `py_normalizar(s)`, `py_advogado_de(s)`, `py_oab_de(s)`, `py_mascarar_cpf(s)`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/dados/test_conexao.py`:
```python
import hashlib
from app.dados.conexao import (
    abrir_conexao, SHA256_ESPERADO, py_mascarar_cpf, py_oab_de, py_normalizar,
)


def test_banco_integro():
    with open("data/desafio.sqlite", "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert digest == SHA256_ESPERADO


def test_conexao_e_readonly():
    c = abrir_conexao()
    try:
        c.execute("create table x(a)")
        assert False, "deveria ser somente leitura"
    except Exception as e:
        assert "readonly" in str(e).lower() or "read-only" in str(e).lower()


def test_funcoes_sql():
    c = abrir_conexao()
    assert c.execute("select normalizar('  SÃO  José ')").fetchone()[0] == "sao jose"
    assert c.execute("select oab_de('Dr. X — OAB/SC 99.651')").fetchone()[0] == "OAB/SC 99.651"
    assert c.execute("select mascarar_cpf('999.550.862-21')").fetchone()[0] == "***.550.862-**"


def test_funcoes_python_espelham():
    assert py_normalizar("SÃO José") == "sao jose"
    assert py_oab_de("Dra. Y — OAB/SC 99.154") == "OAB/SC 99.154"
    assert py_mascarar_cpf("999.550.862-21") == "***.550.862-**"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/dados/test_conexao.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar `app/dados/conexao.py`**

Depende de `app.dados.visoes.criar_visoes` (Tarefa 4). Para manter esta tarefa independente e testável, `criar_visoes` é importado dentro de `abrir_conexao`; se o módulo `visoes` ainda não existir, o teste desta tarefa que usa visões seria adiado — mas aqui os testes não usam visões, só funções e readonly. Implementar com um stub local de `criar_visoes` que será substituído na Tarefa 4:
```python
import re
import sqlite3
import unicodedata

from app.config import get_settings

SHA256_ESPERADO = "8a90b47cdc3b07bcb395ffe0e81c3d56dd33946fa047dec7dc86499767690c43"

_RX_OAB = re.compile(r"OAB/[A-Z]{2}\s+[\d.]+")
_RX_ADV = re.compile(r"^(Dra?\.\s+.+?)\s+—\s+OAB/[A-Z]{2}\s+[\d.]+")


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
    if not s:
        return s
    # CPF: 999.550.862-21 -> ***.550.862-**  (CNPJ, com "/", não é mascarado)
    if "/" in s:
        return s
    return re.sub(r"^\d{3}\.(\d{3}\.\d{3})-\d{2}$", r"***.\1-**", s.strip())


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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/dados/test_conexao.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/dados/conexao.py tests/dados/test_conexao.py
git commit -m "feat: conexão readonly, funções SQL e verificação de integridade"
```

---

## Task 4: Visões normalizadas

**Files:**
- Create: `app/dados/visoes.py`, `tests/dados/test_visoes.py`

**Interfaces:**
- Consumes: `abrir_conexao`, `py_mascarar_cpf`.
- Produces: `criar_visoes(conn: sqlite3.Connection, mascarar: bool = True) -> None` — cria as TEMP VIEW `v_processo, v_partes, v_documentos, v_movimentacoes, v_magistrados, v_unidades`. Colunas conforme a spec §4.4.

- [ ] **Step 1: Escrever o teste que falha**

`tests/dados/test_visoes.py`:
```python
from app.dados.conexao import abrir_conexao


def um(c, sql, *a):
    return c.execute(sql, a).fetchone()


def test_situacao_normalizada():
    c = abrir_conexao()
    # 12 grafias colapsam em 4; 'julgado' é uma delas
    valores = {r[0] for r in c.execute("select distinct situacao from v_processo")}
    assert valores == {"Julgado", "Arquivado", "Em andamento", "Suspenso"}


def test_comarca_vem_da_unidade():
    c = abrir_conexao()
    # Joinville julgados: 190 pela unidade (não 168 pela grafia crua de processo.comarca)
    n = um(c, "select count(*) from v_processo where comarca = 'Joinville' and situacao = 'Julgado'")[0]
    assert n == 190


def test_partes_usa_polo_e_mascara_cpf():
    c = abrir_conexao()
    r = um(c, """select cpf_cnpj from v_partes
                 where numero = '0000001-15.2022.8.99.9012' and polo = 'ativo'""")
    assert r[0] == "***.550.862-**"


def test_documentos_extrai_advogado():
    c = abrir_conexao()
    r = um(c, """select advogado, oab from v_documentos
                 where numero = '0000001-15.2022.8.99.9012' and tipo = 'Petição Inicial'""")
    assert "Sebastião Krüger" in r[0]
    assert r[1] == "OAB/SC 99.651"


def test_movimentacoes_sem_orfas():
    c = abrir_conexao()
    total = um(c, "select count(*) from v_movimentacoes")[0]
    assert total == 134046 - 402  # exclui as 402 órfãs
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/dados/test_visoes.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/dados/visoes.py`**

```python
import sqlite3

_SITUACAO = ("case lower(trim(p.situacao)) "
             "when 'julgado' then 'Julgado' when 'arquivado' then 'Arquivado' "
             "when 'em andamento' then 'Em andamento' when 'suspenso' then 'Suspenso' "
             "else p.situacao end")


def criar_visoes(conn: sqlite3.Connection, mascarar: bool = True) -> None:
    cpf = "mascarar_cpf(pa.documento)" if mascarar else "pa.documento"
    conn.executescript(f"""
    CREATE TEMP VIEW v_processo AS
      SELECT p.id, p.numero, p.classe, p.assunto,
             u.comarca AS comarca, u.vara AS vara, u.status AS unidade_status,
             m.nome AS magistrado, m.situacao AS magistrado_situacao,
             p.magistrado_id, p.unidade_id,
             p.dt_aut AS data_autuacao, p.data_sentenca, p.valor_causa,
             {_SITUACAO} AS situacao, p.situacao AS situacao_original
      FROM processo p
      JOIN unidade u ON u.id = p.unidade_id
      LEFT JOIN magistrado m ON m.id = p.magistrado_id;

    CREATE TEMP VIEW v_partes AS
      SELECT pp.processo_id, pr.numero, pp.polo, pa.nome,
             {cpf} AS cpf_cnpj, pa.tipo AS tipo_cadastral
      FROM processo_parte pp
      JOIN parte pa ON pa.id = pp.parte_id
      JOIN processo pr ON pr.id = pp.processo_id;

    CREATE TEMP VIEW v_documentos AS
      SELECT d.id, d.processo_id, pr.numero, d.tipo, d.autor,
             advogado_de(d.autor) AS advogado, oab_de(d.autor) AS oab,
             d.dt_juntada AS data_juntada, d.num_paginas AS paginas, d.texto
      FROM documento d JOIN processo pr ON pr.id = d.processo_id;

    CREATE TEMP VIEW v_movimentacoes AS
      SELECT mv.id, mv.processo_id, pr.numero, mv.data_mov AS data,
             mv.codigo, mv.descricao
      FROM movimentacao mv JOIN processo pr ON pr.id = mv.processo_id;

    CREATE TEMP VIEW v_magistrados AS
      SELECT m.id, m.nome, u.comarca, u.vara, m.situacao, m.data_inicio
      FROM magistrado m LEFT JOIN unidade u ON u.id = m.unidade_id;

    CREATE TEMP VIEW v_unidades AS
      SELECT id, comarca, vara, status, dt_ini AS data_inicio FROM unidade;
    """)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/dados/test_visoes.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/dados/visoes.py tests/dados/test_visoes.py
git commit -m "feat: visões normalizadas (situação, comarca, polo, advogado, órfãs)"
```

---

## Task 5: Alertas de qualidade

**Files:**
- Create: `app/dados/alertas.py`, `tests/dados/test_alertas.py`

**Interfaces:**
- Consumes: conexão com visões; `py_oab_de`.
- Produces: `alertas_do_processo(conn, processo_id: int) -> list[str]` — lista de frases de alerta (vazia se nenhum). Regras da spec §4.5.

- [ ] **Step 1: Escrever o teste que falha**

`tests/dados/test_alertas.py` (fixtures reais confirmadas no banco):
```python
import pytest
from app.dados.conexao import abrir_conexao
from app.dados.alertas import alertas_do_processo


@pytest.fixture
def conn():
    return abrir_conexao()


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
    assert "assinad" in txt.lower()


def test_acordo_nao_alerta_assinatura(conn):
    # processo com Petição de Acordo (duas assinaturas) não gera alerta de assinatura
    txt = _junta(conn, "0000001-57.2023.8.99.9019")
    assert "assinad" not in txt.lower()


def test_audiencia_data_divergente(conn):
    txt = _junta(conn, "0000001-57.2023.8.99.9019")
    assert "audiência" in txt.lower()


def test_processo_sem_alertas(conn):
    assert alertas_do_processo(conn, _id(conn, "0000001-15.2022.8.99.9012")) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/dados/test_alertas.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/dados/alertas.py`**

```python
import re
import sqlite3

_RX_VALOR = re.compile(r"valor de R\$ ([\d.]+,\d{2})")
_RX_ASS = re.compile(r"(Dra?\.\s+[^\n—]+?)\s+—\s+(OAB/[A-Z]{2}\s+[\d.]+)\s*$")


def _brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def alertas_do_processo(conn: sqlite3.Connection, processo_id: int) -> list[str]:
    p = conn.execute("select * from v_processo where id=?", (processo_id,)).fetchone()
    if p is None:
        return []
    a: list[str] = []
    docs = conn.execute("select * from v_documentos where processo_id=? order by data_juntada, id",
                        (processo_id,)).fetchall()
    partes = conn.execute("select * from v_partes where processo_id=?", (processo_id,)).fetchall()

    if not docs:
        a.append("Nenhum documento juntado a este processo no banco: fatos, pedidos, "
                 "fundamentos, decisões e advogados não estão disponíveis.")

    if p["magistrado_id"] is None:
        outros = conn.execute("select nome from v_magistrados where comarca=? and vara=?",
                              (p["comarca"], p["vara"])).fetchall()
        base = ("Nenhum magistrado vinculado a este processo no cadastro. Atos assinados por "
                "\"Juiz(a) de Direito em exercício\".")
        if outros:
            nomes = ", ".join(o["nome"] for o in outros)
            base += (f" Magistrado(s) lotado(s) na unidade, sem vínculo confirmado com o "
                     f"processo: {nomes}.")
        a.append(base)

    for pt in partes:
        if (pt["tipo_cadastral"], pt["polo"]) in (("autor", "passivo"), ("réu", "ativo")):
            a.append(f"A parte {pt['nome']} tem tipo cadastral '{pt['tipo_cadastral']}', mas "
                     f"figura no polo {pt['polo']} deste processo (vale o polo).")

    if p["situacao"] == "Julgado" and p["data_sentenca"] is None:
        mov = conn.execute("""select min(data) from v_movimentacoes where processo_id=?
                              and (descricao like 'Sentença%' or descricao like 'Homologação%')""",
                           (processo_id,)).fetchone()[0]
        extra = f" A movimentação de sentença é de {mov}." if mov else ""
        a.append("Cadastro indica 'Julgado', mas sem data de sentença registrada." + extra)

    v = p["valor_causa"]
    valor_pet = None
    for d in docs:
        if d["tipo"] == "Petição Inicial" and (m := _RX_VALOR.search(d["texto"] or "")):
            valor_pet = m.group(1)
            break
    if v is None:
        msg = "Valor da causa não informado no cadastro."
        if valor_pet:
            msg += f" A petição inicial menciona R$ {valor_pet}."
        a.append(msg)
    elif v == 0:
        msg = "Valor da causa registrado como R$ 0,00 no cadastro."
        if valor_pet:
            msg += f" A petição inicial menciona R$ {valor_pet}."
        a.append(msg)
    elif v >= 9_999_999_999:
        a.append("Valor da causa atípico no cadastro (possível marcador de dado ausente).")
    elif valor_pet:
        vt = float(valor_pet.replace(".", "").replace(",", "."))
        if abs(vt - v) > 0.01:
            a.append(f"Valor da causa no cadastro ({_brl(v)}) difere do da petição inicial "
                     f"(R$ {valor_pet}).")

    if p["data_autuacao"] is None:
        a.append("Data de autuação não informada no cadastro.")

    for d in docs:
        m = _RX_ASS.search((d["texto"] or "").strip())
        oab_autor = d["oab"]
        if m and oab_autor and m.group(2).strip() != oab_autor and oab_autor not in (d["texto"] or ""):
            a.append(f"O documento [Doc {d['id']} – {d['tipo']}] está cadastrado com autor "
                     f"{d['autor']}, mas a assinatura no texto é de {m.group(1)} ({m.group(2)}).")

    for d in docs:
        if d["tipo"] == "Ata de Audiência":
            datas_mov = {r["data"] for r in conn.execute(
                "select data from v_movimentacoes where processo_id=? and descricao like 'Audiência%Realizada'",
                (processo_id,)).fetchall()}
            if datas_mov and d["data_juntada"] not in datas_mov:
                a.append(f"A data da ata de audiência [Doc {d['id']}] ({d['data_juntada']}) difere "
                         f"da(s) data(s) de 'Audiência ... Realizada' nas movimentações "
                         f"({', '.join(sorted(datas_mov))}).")
    return a
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/dados/test_alertas.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add app/dados/alertas.py tests/dados/test_alertas.py
git commit -m "feat: alertas de qualidade por processo"
```

---

## Task 6: Ferramentas do agente (dossiê, busca, SQL protegido)

**Files:**
- Create: `app/dados/ferramentas.py`, `tests/dados/test_ferramentas.py`

**Interfaces:**
- Consumes: `abrir_conexao`, `normalizar_numero`, `alertas_do_processo`.
- Produces:
  - `obter_dossie(numero: str, conn=None) -> dict`
  - `buscar_processos(conn=None, **filtros) -> dict` (filtros: `parte, cpf_cnpj, classe, assunto, comarca, situacao`)
  - `consultar_sql(sql: str, conn=None) -> dict`
  - `DEFINICOES_TOOLS: list[dict]` — as definições no formato de function-calling da OpenAI.
- Regra do authorizer: permite SELECT/READ/FUNCTION/RECURSIVE; leitura de tabela base só quando a origem é uma visão (`v_*`); nega o resto. Um comando por vez; timeout de 5 s; teto de 50 linhas.

- [ ] **Step 1: Escrever o teste que falha**

`tests/dados/test_ferramentas.py`:
```python
import pytest
from app.dados import ferramentas as F


def test_dossie_processo_completo():
    r = F.obter_dossie("0000001-15.2022.8.99.9012")
    assert r["encontrado"] is True
    assert len(r["documentos"]) == 8
    assert any("Krüger" in adv["nome"] for adv in r["advogados"])
    assert r["alertas"] == []


def test_dossie_numero_dv_invalido():
    r = F.obter_dossie("0000001-16.2022.8.99.9012")
    assert r["encontrado"] is False
    assert "verificador" in r["erro"].lower()


def test_dossie_inexistente():
    r = F.obter_dossie("0009999-69.2024.8.99.9001")  # DV válido, não existe
    assert r["encontrado"] is False
    assert "não encontrado" in r["erro"].lower()


def test_busca_por_parte():
    r = F.buscar_processos(parte="Financeira Araucária")
    assert r["total"] >= 1
    assert len(r["processos"]) <= 20


def test_sql_agregado_ok():
    r = F.consultar_sql(
        "select count(*) as n from v_processo where comarca='Joinville' and situacao='Julgado'")
    assert r["linhas"][0][0] == 190


def test_sql_bloqueia_tabela_base():
    r = F.consultar_sql("select count(*) from processo")
    assert "erro" in r


def test_sql_bloqueia_escrita():
    r = F.consultar_sql("delete from processo")
    assert "erro" in r


def test_sql_um_comando():
    r = F.consultar_sql("select 1; drop table processo")
    assert "erro" in r
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/dados/test_ferramentas.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/dados/ferramentas.py`**

```python
import sqlite3
import time

from app.dados.conexao import abrir_conexao
from app.dados.alertas import alertas_do_processo
from app.dados.numero_cnj import normalizar_numero

_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)
_OK_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, _RECURSIVE}
_POLO_ATIVO = {"Petição Inicial", "Emenda à Inicial", "Réplica"}
_POLO_PASSIVO = {"Contestação", "Exceção de Pré-Executividade", "Embargos à Execução Fiscal"}


def _polo_inferido(tipo: str) -> str | None:
    if tipo in _POLO_ATIVO:
        return "ativo"
    if tipo in _POLO_PASSIVO:
        return "passivo"
    return None


def _proc(conn, numero):
    fmt, erro = normalizar_numero(numero)
    if erro:
        return None, {"encontrado": False, "numero": fmt, "erro": erro}
    p = conn.execute("select * from v_processo where numero=?", (fmt,)).fetchone()
    if p is None:
        return None, {"encontrado": False, "numero": fmt,
                      "erro": "Processo não encontrado no banco."}
    return p, None


def obter_dossie(numero: str, conn=None) -> dict:
    conn = conn or abrir_conexao()
    p, err = _proc(conn, numero)
    if err:
        return err
    pid = p["id"]
    partes = [dict(r) for r in conn.execute(
        "select polo, nome, cpf_cnpj, tipo_cadastral from v_partes where processo_id=? "
        "order by polo, nome", (pid,))]
    movs = [dict(r) for r in conn.execute(
        "select data, descricao from v_movimentacoes where processo_id=? order by data, id", (pid,))]
    docs_rows = conn.execute(
        "select id, tipo, autor, advogado, oab, data_juntada, paginas, texto "
        "from v_documentos where processo_id=? order by data_juntada, id", (pid,)).fetchall()
    advogados: dict[tuple, dict] = {}
    ministerio = []
    for d in docs_rows:
        if d["oab"] and d["advogado"]:
            adv = advogados.setdefault((d["advogado"], d["oab"]), {
                "nome": d["advogado"], "oab": d["oab"], "documentos": [],
                "polo_inferido": _polo_inferido(d["tipo"])})
            adv["documentos"].append(f"Doc {d['id']} – {d['tipo']}")
        elif "Ministério Público" in (d["tipo"] or "") or "Promotor" in (d["autor"] or ""):
            ministerio.append({"documento": f"Doc {d['id']} – {d['tipo']}", "autor": d["autor"]})
    return {
        "encontrado": True,
        "processo": {k: p[k] for k in ("numero", "classe", "assunto", "comarca", "vara",
                                       "magistrado", "magistrado_situacao", "data_autuacao",
                                       "data_sentenca", "valor_causa", "situacao")},
        "partes": partes,
        "advogados": list(advogados.values()),
        "ministerio_publico": ministerio,
        "movimentacoes": movs,
        "documentos": [{"id": d["id"], "tipo": d["tipo"], "autor": d["autor"],
                        "data_juntada": d["data_juntada"], "paginas": d["paginas"],
                        "texto": d["texto"]} for d in docs_rows],
        "alertas": alertas_do_processo(conn, pid),
    }


def buscar_processos(conn=None, parte=None, cpf_cnpj=None, classe=None,
                     assunto=None, comarca=None, situacao=None) -> dict:
    conn = conn or abrir_conexao()
    cond, args = [], []
    if parte or cpf_cnpj:
        sub = "select processo_id from v_partes where 1=1"
        if parte:
            sub += " and normalizar(nome) like '%' || normalizar(?) || '%'"; args.append(parte)
        if cpf_cnpj:
            import re
            sub += " and replace(replace(replace(cpf_cnpj,'.',''),'-',''),'/','') "\
                   "like '%' || ? || '%'"; args.append(re.sub(r"\D", "", cpf_cnpj))
        cond.append(f"id in ({sub})")
    for campo, valor in (("classe", classe), ("assunto", assunto),
                         ("comarca", comarca), ("situacao", situacao)):
        if valor:
            cond.append(f"normalizar({campo}) = normalizar(?)"); args.append(valor)
    if not cond:
        return {"erro": "Informe ao menos um filtro de busca."}
    where = " and ".join(cond)
    total = conn.execute(f"select count(*) from v_processo where {where}", args).fetchone()[0]
    rows = conn.execute(
        f"select numero, classe, assunto, comarca, situacao from v_processo where {where} "
        f"order by id limit 20", args).fetchall()
    resultados = []
    for r in rows:
        partes = conn.execute("select polo, nome from v_partes where numero=? order by polo",
                              (r["numero"],)).fetchall()
        resultados.append({**dict(r),
                           "partes": [f"{x['polo']}: {x['nome']}" for x in partes]})
    return {"total": total, "processos": resultados, "truncado": total > 20}


def consultar_sql(sql: str, conn=None) -> dict:
    conn = conn or abrir_conexao()

    def _auth(action, a1, a2, dbname, origem):
        if action in _OK_ACTIONS:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            return sqlite3.SQLITE_OK if (dbname == "temp" or origem is not None) else sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_DENY

    conn.set_authorizer(_auth)
    limite = time.monotonic() + 5.0
    conn.set_progress_handler(lambda: int(time.monotonic() > limite), 10_000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(51)
        cols = [d[0] for d in cur.description or []]
        return {"sql": sql, "colunas": cols, "linhas": [list(r) for r in rows[:50]],
                "truncado": len(rows) > 50}
    except sqlite3.Error as e:
        return {"sql": sql, "erro": f"{type(e).__name__}: {e}"}
    finally:
        conn.set_authorizer(None)
        conn.set_progress_handler(None, 0)


DEFINICOES_TOOLS = [
    {"type": "function", "function": {
        "name": "obter_dossie",
        "description": "Dossiê completo de um processo: cadastro, partes por polo, advogados "
                       "identificados, Ministério Público, movimentações e íntegra dos documentos "
                       "(com id para citação), além de alertas de qualidade dos dados.",
        "parameters": {"type": "object", "properties": {
            "numero": {"type": "string", "description": "Número CNJ, com ou sem pontuação."}},
            "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "buscar_processos",
        "description": "Localiza processos por parte, CPF/CNPJ, classe, assunto, comarca ou "
                       "situação (ao menos um). Retorna até 20 resultados.",
        "parameters": {"type": "object", "properties": {
            "parte": {"type": "string"}, "cpf_cnpj": {"type": "string"},
            "classe": {"type": "string"}, "assunto": {"type": "string"},
            "comarca": {"type": "string"}, "situacao": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "consultar_sql",
        "description": "Executa UMA consulta SQL SELECT (somente leitura) nas VISÕES v_processo, "
                       "v_partes, v_documentos, v_movimentacoes, v_magistrados, v_unidades. "
                       "Até 50 linhas.",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string"}}, "required": ["sql"]}}},
]

IMPL = {"obter_dossie": obter_dossie, "buscar_processos": buscar_processos,
        "consultar_sql": consultar_sql}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/dados/test_ferramentas.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add app/dados/ferramentas.py tests/dados/test_ferramentas.py
git commit -m "feat: ferramentas do agente (dossiê, busca, SQL protegido)"
```

---

## Task 7: Cliente LLM (httpx, streaming)

**Files:**
- Create: `app/agente/__init__.py`, `app/agente/llm.py`, `tests/agente/__init__.py`, `tests/agente/test_llm.py`

**Interfaces:**
- Consumes: `get_settings`.
- Produces:
  - `async def stream_completion(mensagens: list[dict], tools: list[dict]) -> AsyncIterator[dict]` — cada item é um evento normalizado: `{"tipo": "texto", "delta": str}`, `{"tipo": "tool_calls", "tool_calls": [...]}`, `{"tipo": "reasoning", "reasoning_details": [...]}`, `{"tipo": "uso", "uso": {...}}`, `{"tipo": "fim", "finish": str}`.
  - `custo_de(uso: dict) -> float` — lê `uso.get("cost")` com fallback 0.0.
  - `cliente_http() -> httpx.AsyncClient` — respeita `force_ipv4` (transport com `local_address="0.0.0.0"`).
- Notas: monta o corpo com `provider={"quantizations": [...], "require_parameters": True, "data_collection": "deny", "allow_fallbacks": True}`, `reasoning={"effort": settings.reasoning_effort}`, `usage={"include": True}`, `models=[modelo, reserva]`. Parseia linhas SSE `data:` até `[DONE]`.

- [ ] **Step 1: Escrever o teste que falha**

Testa o parser SSE e o cálculo de custo com respostas falsas, sem rede. O parser fica numa função pura `parse_linha_sse(linha, acumulador)` reusável.

`tests/agente/test_llm.py`:
```python
from app.agente.llm import custo_de, montar_corpo


def test_custo_com_e_sem_campo():
    assert custo_de({"cost": 0.0021}) == 0.0021
    assert custo_de({}) == 0.0  # provedor omitiu 'cost' — Review Focus
    assert custo_de({"prompt_tokens": 10}) == 0.0


def test_corpo_tem_roteamento_e_reasoning():
    corpo = montar_corpo([{"role": "user", "content": "oi"}], tools=[])
    assert corpo["provider"]["data_collection"] == "deny"
    assert "fp8" in corpo["provider"]["quantizations"]
    assert corpo["provider"]["require_parameters"] is True
    assert corpo["reasoning"]["effort"] == "high"
    assert corpo["stream"] is True
    assert corpo["models"][0] == "deepseek/deepseek-v4.1-flash"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agente/test_llm.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/agente/llm.py`**

```python
import json
from typing import AsyncIterator

import httpx

from app.config import get_settings

_QUANT = ["fp8", "mxfp8", "bf16", "fp16", "fp32"]


def custo_de(uso: dict) -> float:
    try:
        return float(uso.get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def montar_corpo(mensagens: list[dict], tools: list[dict]) -> dict:
    s = get_settings()
    corpo = {
        "models": [s.llm_model, s.llm_model_reserva],
        "messages": mensagens,
        "stream": True,
        "usage": {"include": True},
        "provider": {"quantizations": _QUANT, "require_parameters": True,
                     "data_collection": "deny", "allow_fallbacks": True},
        "reasoning": {"effort": s.reasoning_effort},
    }
    if tools:
        corpo["tools"] = tools
    return corpo


def cliente_http() -> httpx.AsyncClient:
    s = get_settings()
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0") if s.force_ipv4 else None
    return httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0), transport=transport)


async def stream_completion(mensagens: list[dict], tools: list[dict]) -> AsyncIterator[dict]:
    s = get_settings()
    corpo = montar_corpo(mensagens, tools)
    headers = {"Authorization": f"Bearer {s.openrouter_api_key}",
               "Content-Type": "application/json"}
    tool_acc: dict[int, dict] = {}
    reasoning_acc: list[dict] = []
    async with cliente_http() as cli:
        async with cli.stream("POST", f"{s.llm_base_url}/chat/completions",
                              headers=headers, json=corpo) as resp:
            if resp.status_code != 200:
                erro = (await resp.aread()).decode(errors="replace")[:500]
                raise RuntimeError(f"HTTP {resp.status_code}: {erro}")
            async for linha in resp.aiter_lines():
                if not linha.startswith("data:"):
                    continue
                dado = linha[5:].strip()
                if dado == "[DONE]":
                    break
                obj = json.loads(dado)
                if obj.get("usage"):
                    yield {"tipo": "uso", "uso": obj["usage"]}
                for ch in obj.get("choices", []):
                    delta = ch.get("delta") or {}
                    if delta.get("content"):
                        yield {"tipo": "texto", "delta": delta["content"]}
                    if delta.get("reasoning_details"):
                        reasoning_acc.extend(delta["reasoning_details"])
                    for tc in delta.get("tool_calls") or []:
                        i = tc.get("index", 0)
                        slot = tool_acc.setdefault(i, {"id": tc.get("id"), "type": "function",
                                                       "function": {"name": "", "arguments": ""}})
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                    if ch.get("finish_reason"):
                        if reasoning_acc:
                            yield {"tipo": "reasoning", "reasoning_details": reasoning_acc}
                        if tool_acc:
                            yield {"tipo": "tool_calls",
                                   "tool_calls": [tool_acc[k] for k in sorted(tool_acc)]}
                        yield {"tipo": "fim", "finish": ch["finish_reason"]}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/agente/test_llm.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/agente/__init__.py app/agente/llm.py tests/agente/
git commit -m "feat: cliente LLM httpx com streaming e roteamento de privacidade"
```

---

## Task 8: Sessão (histórico, foco, custo, compactação)

**Files:**
- Create: `app/agente/sessao.py`, `tests/agente/test_sessao.py`

**Interfaces:**
- Consumes: nada externo.
- Produces: classe `Sessao` com: `historico: list[dict]`, `processo_em_foco: str | None`, `custo_total: float`, métodos `adicionar(msg: dict)`, `definir_foco(numero, resumo: dict)`, `compactar_dossies_antigos()`, `linha_de_contexto() -> str`. E um registro em memória: `SESSOES: dict[str, Sessao]`, `obter_sessao(id: str) -> Sessao`, `nova_sessao() -> str`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/agente/test_sessao.py`:
```python
from app.agente.sessao import Sessao


def test_linha_de_contexto_sem_foco():
    s = Sessao()
    assert "nenhum" in s.linha_de_contexto().lower()


def test_definir_foco():
    s = Sessao()
    s.definir_foco("0000001-15.2022.8.99.9012",
                   {"classe": "Procedimento Comum Cível", "situacao": "Julgado"})
    linha = s.linha_de_contexto()
    assert "0000001-15.2022.8.99.9012" in linha
    assert "Julgado" in linha


def test_compactar_dossie_antigo():
    s = Sessao()
    # dossiê grande no histórico, como resultado de ferramenta
    s.adicionar({"role": "tool", "tool_call_id": "a", "name": "obter_dossie",
                 "content": "x" * 5000, "_numero": "0000001-15.2022.8.99.9012"})
    s.definir_foco("0000002-97.2022.8.99.9012", {"classe": "c", "situacao": "Em andamento"})
    s.compactar_dossies_antigos()
    alvo = [m for m in s.historico if m.get("_numero") == "0000001-15.2022.8.99.9012"][0]
    assert "omitido" in alvo["content"]
    assert len(alvo["content"]) < 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/agente/test_sessao.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/agente/sessao.py`**

```python
import uuid


class Sessao:
    def __init__(self) -> None:
        self.historico: list[dict] = []
        self.processo_em_foco: str | None = None
        self.foco_resumo: dict = {}
        self.custo_total: float = 0.0

    def adicionar(self, msg: dict) -> None:
        self.historico.append(msg)

    def definir_foco(self, numero: str, resumo: dict) -> None:
        self.processo_em_foco = numero
        self.foco_resumo = resumo

    def linha_de_contexto(self) -> str:
        if not self.processo_em_foco:
            return "Processo em foco: nenhum."
        r = self.foco_resumo
        return (f"Processo em foco: {self.processo_em_foco} "
                f"({r.get('classe', '?')}, {r.get('situacao', '?')}).")

    def compactar_dossies_antigos(self) -> None:
        for m in self.historico:
            num = m.get("_numero")
            if (m.get("role") == "tool" and m.get("name") == "obter_dossie"
                    and num and num != self.processo_em_foco
                    and "omitido" not in m["content"]):
                m["content"] = (f"[dossiê de {num} omitido para poupar contexto; "
                                f"chame obter_dossie de novo se precisar]")


SESSOES: dict[str, Sessao] = {}


def nova_sessao() -> str:
    sid = uuid.uuid4().hex
    SESSOES[sid] = Sessao()
    return sid


def obter_sessao(sid: str) -> Sessao:
    return SESSOES.setdefault(sid, Sessao())
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/agente/test_sessao.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/agente/sessao.py tests/agente/test_sessao.py
git commit -m "feat: sessão com foco de processo e compactação de dossiê"
```

---

## Task 9: Prompt de sistema e laço do agente

**Files:**
- Create: `app/agente/prompt.md`, `app/agente/ciclo.py`, `tests/agente/test_ciclo.py`

**Interfaces:**
- Consumes: `stream_completion` (injetável), `DEFINICOES_TOOLS`, `IMPL`, `Sessao`, `obter_dossie`.
- Produces: `async def responder(sessao: Sessao, pergunta: str, *, stream_fn=stream_completion) -> AsyncIterator[dict]` — emite eventos de alto nível: `{"tipo":"ferramenta", ...}`, `{"tipo":"texto","delta":...}`, `{"tipo":"processo","ficha":...}`, `{"tipo":"fim","uso":...}`, `{"tipo":"erro","mensagem":...}`. Máximo de 8 passos. Sobre pergunta sem número e sem foco, ainda deixa o modelo decidir (o prompt manda pedir o número) — mas a ferramenta com número vazio retorna erro de formato, não exceção.
- `carregar_prompt() -> str` lê `prompt.md`.

- [ ] **Step 1: Escrever o prompt `app/agente/prompt.md`**

Conteúdo conforme a spec §5.3 (12 itens). Texto integral em português. Termina com a instrução de que a linha "Processo em foco: ..." será fornecida a cada turno.

- [ ] **Step 2: Escrever o teste que falha (LLM falso roteirizado)**

`tests/agente/test_ciclo.py`:
```python
import json
import pytest
from app.agente.sessao import Sessao
from app.agente import ciclo


def _fake_stream(roteiro):
    """roteiro: lista de 'turnos'; cada turno é lista de eventos a emitir."""
    turnos = iter(roteiro)

    async def stream_fn(mensagens, tools):
        for ev in next(turnos):
            yield ev
    return stream_fn


@pytest.mark.anyio
async def test_uma_ferramenta_depois_texto():
    roteiro = [
        [{"tipo": "tool_calls", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "obter_dossie",
                          "arguments": json.dumps({"numero": "0000001-15.2022.8.99.9012"})}}]},
         {"tipo": "uso", "uso": {"cost": 0.001}}, {"tipo": "fim", "finish": "tool_calls"}],
        [{"tipo": "texto", "delta": "Processo julgado."},
         {"tipo": "uso", "uso": {"cost": 0.001}}, {"tipo": "fim", "finish": "stop"}],
    ]
    s = Sessao()
    eventos = [e async for e in ciclo.responder(s, "Já foi julgado?", stream_fn=_fake_stream(roteiro))]
    tipos = [e["tipo"] for e in eventos]
    assert "ferramenta" in tipos and "texto" in tipos
    assert s.processo_em_foco == "0000001-15.2022.8.99.9012"
    assert any(e["tipo"] == "fim" for e in eventos)


@pytest.mark.anyio
async def test_limite_de_passos():
    # sempre pede ferramenta: precisa parar em 8 passos sem loop infinito
    turno = [{"tipo": "tool_calls", "tool_calls": [
        {"id": "c", "type": "function",
         "function": {"name": "consultar_sql", "arguments": json.dumps({"sql": "select 1"})}}]},
        {"tipo": "uso", "uso": {"cost": 0.0}}, {"tipo": "fim", "finish": "tool_calls"}]
    s = Sessao()
    eventos = [e async for e in ciclo.responder(s, "loop", stream_fn=_fake_stream([turno] * 20))]
    assert any(e["tipo"] == "erro" or "limite" in str(e).lower() for e in eventos)


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/agente/test_ciclo.py -v`
Expected: FAIL

- [ ] **Step 4: Implementar `app/agente/ciclo.py`**

```python
import json
from pathlib import Path
from typing import AsyncIterator

from app.agente.llm import stream_completion, custo_de
from app.agente.sessao import Sessao
from app.dados.ferramentas import DEFINICOES_TOOLS, IMPL, obter_dossie

_PROMPT = Path(__file__).with_name("prompt.md")
MAX_PASSOS = 8


def carregar_prompt() -> str:
    return _PROMPT.read_text(encoding="utf-8")


def _resumo_resultado(nome, res):
    if isinstance(res, dict) and res.get("erro"):
        return f"erro: {res['erro']}"
    if nome == "consultar_sql":
        return f"{len(res.get('linhas', []))} linha(s)"
    if nome == "buscar_processos":
        return f"{res.get('total', 0)} encontrado(s)"
    return f"{len(res.get('documentos', []))} docs, {len(res.get('alertas', []))} alerta(s)"


async def responder(sessao: Sessao, pergunta: str, *, stream_fn=stream_completion) -> AsyncIterator[dict]:
    if not sessao.historico:
        sessao.adicionar({"role": "system", "content": carregar_prompt()})
    sessao.adicionar({"role": "user",
                      "content": f"{sessao.linha_de_contexto()}\n\nPergunta: {pergunta}"})
    uso_total = {"prompt": 0, "completion": 0, "cost": 0.0}

    for passo in range(MAX_PASSOS):
        texto_buf, tool_calls, reasoning = "", None, None
        try:
            async for ev in stream_fn(
                    [{k: v for k, v in m.items() if not k.startswith("_")} for m in sessao.historico],
                    DEFINICOES_TOOLS):
                if ev["tipo"] == "texto":
                    texto_buf += ev["delta"]
                    yield {"tipo": "texto", "delta": ev["delta"]}
                elif ev["tipo"] == "tool_calls":
                    tool_calls = ev["tool_calls"]
                elif ev["tipo"] == "reasoning":
                    reasoning = ev["reasoning_details"]
                elif ev["tipo"] == "uso":
                    uso_total["cost"] += custo_de(ev["uso"])
                    uso_total["prompt"] += ev["uso"].get("prompt_tokens") or 0
                    uso_total["completion"] += ev["uso"].get("completion_tokens") or 0
        except Exception as e:  # falha de rede/provedor
            yield {"tipo": "erro", "mensagem": f"Falha ao consultar o modelo: {e}"}
            return

        msg = {"role": "assistant", "content": texto_buf}
        if reasoning:
            msg["reasoning_details"] = reasoning
        if tool_calls:
            msg["tool_calls"] = tool_calls
        sessao.adicionar(msg)

        if not tool_calls:
            sessao.custo_total += uso_total["cost"]
            yield {"tipo": "fim", "uso": uso_total}
            return

        for tc in tool_calls:
            nome = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
                res = IMPL[nome](**args)
            except Exception as e:
                res = {"erro": f"{type(e).__name__}: {e}"}
            numero = None
            if nome == "obter_dossie" and isinstance(res, dict) and res.get("encontrado"):
                p = res["processo"]
                numero = p["numero"]
                sessao.definir_foco(numero, {"classe": p["classe"], "situacao": p["situacao"]})
                sessao.compactar_dossies_antigos()
                yield {"tipo": "processo", "ficha": {**p, "alertas": res["alertas"]}}
            yield {"tipo": "ferramenta", "nome": nome, "args": args,
                   "resumo": _resumo_resultado(nome, res)}
            msg_tool = {"role": "tool", "tool_call_id": tc.get("id"), "name": nome,
                        "content": json.dumps(res, ensure_ascii=False)}
            if numero:
                msg_tool["_numero"] = numero
            sessao.adicionar(msg_tool)

    sessao.custo_total += uso_total["cost"]
    yield {"tipo": "erro", "mensagem": "Limite de passos atingido sem concluir a resposta."}
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/agente/test_ciclo.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add app/agente/prompt.md app/agente/ciclo.py tests/agente/test_ciclo.py
git commit -m "feat: prompt de sistema e laço do agente com ferramentas"
```

---

## Task 10: Verificação — citações

**Files:**
- Create: `app/verificacao/__init__.py`, `app/verificacao/citacoes.py`, `tests/verificacao/__init__.py`, `tests/verificacao/test_citacoes.py`

**Interfaces:**
- Produces: `verificar_citacoes(resposta: str, docs_vistos: set[int], movs_vistas: set[str], houve_sql: bool) -> list[dict]` — cada selo `{"tipo":"citacao","status":"ok|alerta","mensagem":str,"trechos":list[str]}`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/verificacao/test_citacoes.py`:
```python
from app.verificacao.citacoes import verificar_citacoes


def test_doc_valido():
    selos = verificar_citacoes("Conforme [Doc 93 – Sentença], improcedente.",
                               docs_vistos={93}, movs_vistas=set(), houve_sql=False)
    assert all(s["status"] == "ok" for s in selos)


def test_doc_inexistente_alerta():
    selos = verificar_citacoes("Segundo [Doc 999], ...",
                               docs_vistos={93}, movs_vistas=set(), houve_sql=False)
    assert any(s["status"] == "alerta" and "999" in " ".join(s["trechos"]) for s in selos)


def test_sql_sem_consulta_alerta():
    selos = verificar_citacoes("O total é 190 [SQL].",
                               docs_vistos=set(), movs_vistas=set(), houve_sql=False)
    assert any(s["status"] == "alerta" for s in selos)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/verificacao/test_citacoes.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/verificacao/citacoes.py`**

```python
import re

_RX_DOC = re.compile(r"\[Doc\.?\s*(\d+)", re.I)
_RX_SQL = re.compile(r"\[SQL", re.I)


def verificar_citacoes(resposta: str, docs_vistos: set[int], movs_vistas: set[str],
                       houve_sql: bool) -> list[dict]:
    selos: list[dict] = []
    docs_citados = {int(x) for x in _RX_DOC.findall(resposta)}
    invalidos = sorted(docs_citados - docs_vistos)
    if docs_citados and not invalidos:
        selos.append({"tipo": "citacao", "status": "ok",
                      "mensagem": f"{len(docs_citados)} citação(ões) de documento conferida(s).",
                      "trechos": []})
    if invalidos:
        selos.append({"tipo": "citacao", "status": "alerta",
                      "mensagem": "Citação de documento não consultado nesta conversa.",
                      "trechos": [f"Doc {n}" for n in invalidos]})
    if _RX_SQL.search(resposta) and not houve_sql:
        selos.append({"tipo": "citacao", "status": "alerta",
                      "mensagem": "Marcou [SQL] sem ter executado consulta neste turno.",
                      "trechos": []})
    return selos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/verificacao/test_citacoes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/verificacao/__init__.py app/verificacao/citacoes.py tests/verificacao/
git commit -m "feat: verificação de citações de fonte"
```

---

## Task 11: Verificação — aspas literais

**Files:**
- Create: `app/verificacao/aspas.py`, `tests/verificacao/test_aspas.py`

**Interfaces:**
- Produces: `verificar_aspas(resposta: str, textos_docs: list[str]) -> list[dict]`. Normaliza caixa/espaços/marcação; considera só trechos com 20+ caracteres; suporta reticências dividindo em fragmentos.

- [ ] **Step 1: Escrever o teste que falha**

`tests/verificacao/test_aspas.py`:
```python
from app.verificacao.aspas import verificar_aspas

DOC = ['A parte autora não se desincumbiu do ônus de comprovar os fatos constitutivos.']


def test_aspas_literais_ok():
    r = 'A juíza afirmou: "não se desincumbiu do ônus de comprovar os fatos constitutivos".'
    selos = verificar_aspas(r, DOC)
    assert all(s["status"] == "ok" for s in selos)


def test_parafrase_alerta():
    r = 'A juíza disse que "a autora não provou nada do que alegou na inicial".'
    selos = verificar_aspas(r, DOC)
    assert any(s["status"] == "alerta" for s in selos)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/verificacao/test_aspas.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/verificacao/aspas.py`**

```python
import re

_RX_ASPAS = re.compile(r'[“"]([^”"\n]{20,}?)[”"]')


def _norm(s: str) -> str:
    s = re.sub(r"[*_`]", "", s).lower().replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def verificar_aspas(resposta: str, textos_docs: list[str]) -> list[dict]:
    corpus = _norm(" ".join(textos_docs))
    literais, suspeitos = 0, []
    for trecho in _RX_ASPAS.findall(resposta):
        frags = [_norm(x) for x in re.split(r"\.\.\.|…|\[\.\.\.\]", trecho) if len(_norm(x)) >= 15]
        if not frags:
            continue
        if all(f in corpus for f in frags):
            literais += 1
        else:
            suspeitos.append(trecho[:120])
    selos = []
    if literais:
        selos.append({"tipo": "aspas", "status": "ok",
                      "mensagem": f"{literais} trecho(s) entre aspas conferido(s) como literal(is).",
                      "trechos": []})
    if suspeitos:
        selos.append({"tipo": "aspas", "status": "alerta",
                      "mensagem": "Trecho entre aspas não encontrado literalmente nos documentos "
                                  "(pode ser paráfrase).", "trechos": suspeitos})
    return selos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/verificacao/test_aspas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/verificacao/aspas.py tests/verificacao/test_aspas.py
git commit -m "feat: verificação de aspas literais"
```

---

## Task 12: Verificação — normas/súmulas

**Files:**
- Create: `app/verificacao/normas.py`, `tests/verificacao/test_normas.py`

**Interfaces:**
- Produces: `verificar_normas(resposta: str, textos_docs: list[str]) -> list[dict]`. Extrai "Súmula N" e "art. N do CPC/CC/CDC/Lei ..." e confere se aparecem nos autos. Marcações `[verificar]` do modelo contam como já sinalizadas (não geram alerta novo).

- [ ] **Step 1: Escrever o teste que falha**

`tests/verificacao/test_normas.py`:
```python
from app.verificacao.normas import verificar_normas

DOC = ['... nos termos do art. 373, inciso I, do Código de Processo Civil ...']


def test_norma_nos_autos_ok():
    selos = verificar_normas("Aplica-se o art. 373 do CPC.", DOC)
    assert all(s["status"] == "ok" for s in selos)


def test_sumula_externa_alerta():
    selos = verificar_normas("Incide a Súmula 403 do STJ.", DOC)
    assert any(s["status"] == "alerta" and "403" in " ".join(s["trechos"]) for s in selos)


def test_marcada_verificar_nao_alerta():
    selos = verificar_normas("Talvez a Súmula 385 do STJ [verificar].", DOC)
    assert all(s["status"] != "alerta" for s in selos)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/verificacao/test_normas.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/verificacao/normas.py`**

```python
import re

_RX_SUMULA = re.compile(r"s[úu]mula\s+(?:vinculante\s+)?n?[º°.]?\s*(\d+)", re.I)
_RX_ART = re.compile(r"art(?:igo|\.)\s*(\d+)", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower())


def verificar_normas(resposta: str, textos_docs: list[str]) -> list[dict]:
    corpus = _norm(" ".join(textos_docs))
    externas = []
    for m in _RX_SUMULA.finditer(resposta):
        ini = max(0, m.start() - 40)
        if "[verificar]" in resposta[m.start():m.end() + 15].lower():
            continue
        if f"súmula {m.group(1)}" not in corpus and f"sumula {m.group(1)}" not in corpus:
            externas.append(f"Súmula {m.group(1)}")
    for m in _RX_ART.finditer(resposta):
        trecho = resposta[m.start():m.end() + 40].lower()
        if "[verificar]" in trecho:
            continue
        if f"art. {m.group(1)}" not in corpus and f"artigo {m.group(1)}" not in corpus:
            externas.append(f"art. {m.group(1)}")
    selos = []
    if externas:
        selos.append({"tipo": "norma", "status": "alerta",
                      "mensagem": "Norma/súmula citada não encontrada nos autos; conferir.",
                      "trechos": sorted(set(externas))})
    else:
        selos.append({"tipo": "norma", "status": "ok",
                      "mensagem": "Referências normativas conferem com os autos ou estão ausentes.",
                      "trechos": []})
    return selos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/verificacao/test_normas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/verificacao/normas.py tests/verificacao/test_normas.py
git commit -m "feat: verificação de normas e súmulas fora dos autos"
```

---

## Task 13: Verificação — minuta

**Files:**
- Create: `app/verificacao/minuta.py`, `tests/verificacao/test_minuta.py`

**Interfaces:**
- Produces:
  - `eh_minuta(resposta: str, pergunta: str) -> bool` — verdadeiro se a resposta traz o aviso, ou a pergunta pede *elaborar/redigir/propor* minuta/sentença (pergunta sobre sentença existente não conta).
  - `verificar_minuta(resposta: str) -> list[dict]` — dispositivo decidido fora de colchetes; nome na assinatura; ausência do aviso.

- [ ] **Step 1: Escrever o teste que falha**

`tests/verificacao/test_minuta.py`:
```python
from app.verificacao.minuta import eh_minuta, verificar_minuta


def test_deteccao_por_pedido():
    assert eh_minuta("...", "Elabore uma minuta de sentença para o processo X")
    assert not eh_minuta("A sentença julgou improcedente.", "Qual foi a sentença?")


def test_decisao_entre_colchetes_ok():
    r = ("MINUTA — PROPOSTA DE TEXTO GERADA POR IA... "
         "Ante o exposto, [JULGO PROCEDENTE / IMPROCEDENTE] o pedido.")
    assert all(s["status"] == "ok" for s in verificar_minuta(r))


def test_decide_merito_alerta():
    r = ("MINUTA — PROPOSTA... Ante o exposto, JULGO PROCEDENTE o pedido, "
         "condenando a ré.")
    assert any(s["status"] == "alerta" for s in verificar_minuta(r))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/verificacao/test_minuta.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/verificacao/minuta.py`**

```python
import re

AVISO = ("MINUTA — PROPOSTA DE TEXTO GERADA POR IA, SUJEITA À REVISÃO DO MAGISTRADO. "
         "NÃO É SENTENÇA PROFERIDA.")
_RX_PEDIDO = re.compile(r"\b(elabore|elaborar|redija|redigir|minute|proponha|propor|"
                        r"faça|escreva)\b.{0,40}(minuta|senten[çc]a)", re.I)
_RX_DISPOSITIVO = re.compile(r"\bjulgo\s+(parcialmente\s+)?(procedente|improcedente)", re.I)


def eh_minuta(resposta: str, pergunta: str) -> bool:
    if "PROPOSTA DE TEXTO GERADA POR IA" in resposta:
        return True
    return bool(_RX_PEDIDO.search(pergunta or ""))


def verificar_minuta(resposta: str) -> list[dict]:
    selos = []
    sem_colchetes = re.sub(r"\[[^\]]*\]", " ", resposta)
    if _RX_DISPOSITIVO.search(sem_colchetes):
        selos.append({"tipo": "minuta", "status": "alerta",
                      "mensagem": "A minuta decide o mérito fora de colchetes; a decisão cabe ao "
                                  "magistrado.", "trechos": []})
    else:
        selos.append({"tipo": "minuta", "status": "ok",
                      "mensagem": "Dispositivo deixado à decisão do magistrado.", "trechos": []})
    if "PROPOSTA DE TEXTO GERADA POR IA" not in resposta:
        selos.append({"tipo": "minuta", "status": "alerta",
                      "mensagem": "Minuta sem o aviso de proposta (será inserido pela interface).",
                      "trechos": []})
    return selos
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/verificacao/test_minuta.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/verificacao/minuta.py tests/verificacao/test_minuta.py
git commit -m "feat: detecção e verificação de minuta"
```

---

## Task 14: Orquestrador de verificação (selos)

**Files:**
- Create: `app/verificacao/selos.py`, `tests/verificacao/test_selos.py`

**Interfaces:**
- Consumes: as quatro verificações anteriores.
- Produces: `verificar(resposta, pergunta, *, docs_vistos, movs_vistas, houve_sql, textos_docs) -> dict` com `{"selos": list[dict], "eh_minuta": bool}`. Reúne todos os selos e adiciona a verificação de minuta só quando `eh_minuta`.

- [ ] **Step 1: Escrever o teste que falha**

`tests/verificacao/test_selos.py`:
```python
from app.verificacao.selos import verificar


def test_reune_selos_e_marca_minuta():
    r = ("MINUTA — PROPOSTA DE TEXTO GERADA POR IA... [Doc 93] "
         "Ante o exposto, [JULGO IMPROCEDENTE].")
    res = verificar(r, "Elabore uma minuta", docs_vistos={93}, movs_vistas=set(),
                    houve_sql=False, textos_docs=["texto do doc 93"])
    assert res["eh_minuta"] is True
    assert any(s["tipo"] == "minuta" for s in res["selos"])
    assert any(s["tipo"] == "citacao" for s in res["selos"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/verificacao/test_selos.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/verificacao/selos.py`**

```python
from app.verificacao.citacoes import verificar_citacoes
from app.verificacao.aspas import verificar_aspas
from app.verificacao.normas import verificar_normas
from app.verificacao.minuta import eh_minuta, verificar_minuta


def verificar(resposta: str, pergunta: str, *, docs_vistos, movs_vistas, houve_sql,
              textos_docs) -> dict:
    selos = []
    selos += verificar_citacoes(resposta, docs_vistos, movs_vistas, houve_sql)
    selos += verificar_aspas(resposta, textos_docs)
    selos += verificar_normas(resposta, textos_docs)
    minuta = eh_minuta(resposta, pergunta)
    if minuta:
        selos += verificar_minuta(resposta)
    return {"selos": selos, "eh_minuta": minuta}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/verificacao/test_selos.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/verificacao/selos.py tests/verificacao/test_selos.py
git commit -m "feat: orquestrador de verificação (selos)"
```

---

## Task 15: Log de auditoria

**Files:**
- Create: `app/auditoria.py`, `tests/test_auditoria.py`

**Interfaces:**
- Produces: `registrar(evento: dict, caminho='logs/auditoria.jsonl') -> None` (uma linha JSON; cria `logs/` se preciso; nunca grava chaves; CPF já vem mascarado da camada de dados). `custo_acumulado(caminho) -> float` soma o campo `custo` de todas as linhas.

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_auditoria.py`:
```python
import json
from app.auditoria import registrar, custo_acumulado


def test_registra_e_soma(tmp_path):
    p = tmp_path / "aud.jsonl"
    registrar({"pergunta": "oi", "custo": 0.002}, caminho=str(p))
    registrar({"pergunta": "oi2", "custo": 0.003}, caminho=str(p))
    linhas = p.read_text().strip().splitlines()
    assert len(linhas) == 2
    assert json.loads(linhas[0])["pergunta"] == "oi"
    assert abs(custo_acumulado(str(p)) - 0.005) < 1e-9
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_auditoria.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/auditoria.py`**

```python
import json
from datetime import datetime, timezone
from pathlib import Path


def registrar(evento: dict, caminho: str = "logs/auditoria.jsonl") -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    linha = {"ts": datetime.now(timezone.utc).isoformat(), **evento}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def custo_acumulado(caminho: str = "logs/auditoria.jsonl") -> float:
    p = Path(caminho)
    if not p.exists():
        return 0.0
    total = 0.0
    for linha in p.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            total += float(json.loads(linha).get("custo") or 0.0)
    return total
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_auditoria.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/auditoria.py tests/test_auditoria.py
git commit -m "feat: log de auditoria em jsonl"
```

---

## Task 16: API FastAPI com SSE

**Files:**
- Create: `app/main.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: `responder`, `verificar`, `Sessao/obter_sessao/nova_sessao`, `registrar`, `custo_acumulado`, `get_settings`, `abrir_conexao`.
- Produces: app FastAPI com `POST /api/chat` (SSE), `POST /api/sessao/nova`, `GET /api/saude`. O endpoint de chat acumula, ao longo do turno, `docs_vistos`, `movs_vistas`, `houve_sql` e `textos_docs` a partir dos eventos de ferramenta; ao fim do texto, roda `verificar` e emite o evento `verificacao`; grava auditoria; aplica o teto de orçamento antes de começar.
- Eventos SSE conforme a spec §7.

- [ ] **Step 1: Escrever o teste que falha (com agente falso via override)**

`tests/test_api.py`:
```python
from fastapi.testclient import TestClient
import app.main as main


def test_saude():
    c = TestClient(main.app)
    r = c.get("/api/saude")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_chat_stream(monkeypatch):
    async def fake_responder(sessao, pergunta, **kw):
        yield {"tipo": "ferramenta", "nome": "obter_dossie", "args": {}, "resumo": "8 docs",
               "_docs": [{"id": 93, "texto": "trecho literal do documento noventa e três"}]}
        yield {"tipo": "texto", "delta": 'Cita [Doc 93]: "trecho literal do documento".'}
        yield {"tipo": "fim", "uso": {"cost": 0.001}}
    monkeypatch.setattr(main, "responder", fake_responder)
    c = TestClient(main.app)
    sid = c.post("/api/sessao/nova").json()["sessao_id"]
    with c.stream("POST", "/api/chat", json={"sessao_id": sid, "pergunta": "x"}) as r:
        corpo = "".join(chunk for chunk in r.iter_text())
    assert "verificacao" in corpo
    assert "event:" in corpo or "data:" in corpo
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `app/main.py`**

```python
import json
from collections.abc import AsyncIterable

from fastapi import FastAPI
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agente.ciclo import responder
from app.agente.sessao import obter_sessao, nova_sessao
from app.auditoria import registrar, custo_acumulado
from app.config import get_settings
from app.dados.conexao import abrir_conexao, verificar_integridade
from app.verificacao.selos import verificar

app = FastAPI(title="Agente de Consulta Processual")


@app.on_event("startup")
def _valida_banco():
    s = get_settings()
    conn = abrir_conexao()
    tabelas = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}
    faltando = {"processo", "parte", "processo_parte", "documento",
                "movimentacao", "magistrado", "unidade"} - tabelas
    if faltando:
        raise RuntimeError(f"Banco inválido: faltam tabelas {faltando}")


class Pergunta(BaseModel):
    sessao_id: str
    pergunta: str


@app.get("/api/saude")
def saude():
    s = get_settings()
    return {"ok": True, "modelo": s.llm_model,
            "custo_acumulado": round(custo_acumulado(), 4), "orcamento": s.orcamento_usd}


@app.post("/api/sessao/nova")
def sessao_nova():
    return {"sessao_id": nova_sessao()}


@app.post("/api/chat")
async def chat(p: Pergunta) -> EventSourceResponse:
    s = get_settings()
    sessao = obter_sessao(p.sessao_id)

    async def gerar() -> AsyncIterable[ServerSentEvent]:
        if custo_acumulado() > s.orcamento_usd:
            yield ServerSentEvent(event="erro",
                                  data=json.dumps({"mensagem": "Orçamento do protótipo atingido."}))
            return
        docs_vistos: set[int] = set()
        movs_vistas: set[str] = set()
        textos_docs: list[str] = []
        houve_sql = False
        resposta = ""
        uso = {}
        ferramentas_log = []
        async for ev in responder(sessao, p.pergunta):
            if ev["tipo"] == "ferramenta":
                houve_sql = houve_sql or ev["nome"] == "consultar_sql"
                for d in ev.get("_docs", []):
                    docs_vistos.add(d["id"])
                    textos_docs.append(d.get("texto") or "")
                ferramentas_log.append({"nome": ev["nome"], "resumo": ev["resumo"]})
                yield ServerSentEvent(event="ferramenta",
                                      data=json.dumps({k: v for k, v in ev.items()
                                                       if not k.startswith("_")}, ensure_ascii=False))
            elif ev["tipo"] == "texto":
                resposta += ev["delta"]
                yield ServerSentEvent(event="texto", data=json.dumps({"delta": ev["delta"]},
                                                                     ensure_ascii=False))
            elif ev["tipo"] == "processo":
                for d in ev["ficha"].get("_docs", []):
                    docs_vistos.add(d["id"])
                yield ServerSentEvent(event="processo",
                                      data=json.dumps(ev["ficha"], ensure_ascii=False))
            elif ev["tipo"] == "erro":
                yield ServerSentEvent(event="erro", data=json.dumps({"mensagem": ev["mensagem"]},
                                                                    ensure_ascii=False))
            elif ev["tipo"] == "fim":
                uso = ev["uso"]
        ver = verificar(resposta, p.pergunta, docs_vistos=docs_vistos, movs_vistas=movs_vistas,
                        houve_sql=houve_sql, textos_docs=textos_docs)
        yield ServerSentEvent(event="verificacao", data=json.dumps(ver, ensure_ascii=False))
        yield ServerSentEvent(event="fim", data=json.dumps(
            {"uso": uso, "custo_sessao": round(sessao.custo_total, 4)}, ensure_ascii=False))
        registrar({"sessao": p.sessao_id, "pergunta": p.pergunta,
                   "processo_em_foco": sessao.processo_em_foco, "ferramentas": ferramentas_log,
                   "custo": uso.get("cost", 0.0), "selos": ver["selos"]})

    return EventSourceResponse(gerar())


app.mount("/", StaticFiles(directory="app/web/static", html=True), name="web")
```

Nota de interface: a Tarefa 9 deve enriquecer o evento `ferramenta` de `obter_dossie` com uma chave `_docs` (lista de `{"id", "texto"}`), para que a API acumule `docs_vistos`/`textos_docs`. Ajustar `ciclo.responder` para incluir `_docs` no evento `ferramenta` quando o resultado tiver documentos, e no evento `processo` a ficha inclui `_docs`. (Registrado aqui como dependência de interface; o teste `test_api` cobre o consumo.)

- [ ] **Step 4: Ajustar `ciclo.responder` para emitir `_docs`**

No bloco de execução de ferramenta, ao montar o evento `{"tipo":"ferramenta",...}`, se `res` tiver `documentos`, incluir `"_docs": [{"id": d["id"], "texto": d["texto"]} for d in res["documentos"]]`. Rodar `uv run pytest tests/agente/test_ciclo.py` e confirmar que continua PASS.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/test_api.py tests/agente/test_ciclo.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/agente/ciclo.py tests/test_api.py
git commit -m "feat: API FastAPI com streaming SSE e verificação no fim do turno"
```

---

## Task 17: Endpoint de documento (restrito à sessão)

**Files:**
- Modify: `app/main.py`
- Modify: `app/agente/sessao.py` (guardar `docs_por_processo` e `processos_consultados`)
- Create/Modify: `tests/test_api.py` (novo teste)

**Interfaces:**
- Produces: `GET /api/documento/{doc_id}?sessao_id=` → `{"id","tipo","texto",...}` só se o documento pertence a um processo consultado na sessão; caso contrário 403. A sessão passa a registrar `processos_consultados: set[str]` (preenchido em `definir_foco` e em buscas).

- [ ] **Step 1: Escrever o teste que falha**

Adicionar a `tests/test_api.py`:
```python
def test_documento_fora_da_sessao_403():
    c = TestClient(main.app)
    sid = c.post("/api/sessao/nova").json()["sessao_id"]
    # nenhum processo consultado ainda → acesso negado
    r = c.get(f"/api/documento/93?sessao_id={sid}")
    assert r.status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_api.py::test_documento_fora_da_sessao_403 -v`
Expected: FAIL

- [ ] **Step 3: Implementar**

Em `sessao.py`, adicionar `self.processos_consultados: set[str] = set()` e incluir o número em `definir_foco`. Em `main.py`:
```python
@app.get("/api/documento/{doc_id}")
def documento(doc_id: int, sessao_id: str):
    from fastapi import HTTPException
    sessao = obter_sessao(sessao_id)
    conn = abrir_conexao()
    row = conn.execute("select id, numero, tipo, autor, data_juntada, texto "
                       "from v_documentos where id=?", (doc_id,)).fetchone()
    if row is None or row["numero"] not in sessao.processos_consultados:
        raise HTTPException(status_code=403, detail="Documento fora do escopo desta sessão.")
    return dict(row)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/agente/sessao.py tests/test_api.py
git commit -m "feat: endpoint de documento restrito aos processos da sessão"
```

---

## Task 18: Interface web (HTML/CSS/JS)

**Files:**
- Create: `app/web/static/index.html`, `app/web/static/estilo.css`, `app/web/static/app.js`
- Add: `app/web/static/vendor/marked.umd.js`, `app/web/static/vendor/purify.min.js` (baixados)
- Create: `tests/test_estaticos.py`

**Interfaces:**
- Consome a API via `fetch` + leitura do stream SSE. Implementa o layout A: chat à esquerda; painel com abas Fontes / Como cheguei aqui / Processo à direita; faixa de minuta; citações clicáveis; selos.

- [ ] **Step 1: Baixar os vendors e escrever teste de sanidade**

```bash
mkdir -p app/web/static/vendor
curl -4 -sL https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.umd.js -o app/web/static/vendor/marked.umd.js
curl -4 -sL https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.min.js -o app/web/static/vendor/purify.min.js
```
`tests/test_estaticos.py`:
```python
from pathlib import Path


def test_vendors_presentes():
    assert Path("app/web/static/vendor/marked.umd.js").stat().st_size > 1000
    assert Path("app/web/static/vendor/purify.min.js").stat().st_size > 1000


def test_index_referencia_app_js():
    html = Path("app/web/static/index.html").read_text(encoding="utf-8")
    assert "app.js" in html and "estilo.css" in html
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_estaticos.py -v`
Expected: FAIL (index.html ainda não existe)

- [ ] **Step 3: Escrever `index.html`, `estilo.css`, `app.js`**

`index.html`: cabeçalho com o processo em foco; `<main>` com `#chat` e `<aside>` com as três abas; caixa de entrada; inclui `vendor/marked.umd.js`, `vendor/purify.min.js`, `app.js` (todos locais, sem CDN em runtime). `estilo.css`: layout de duas colunas, responsivo, legível em projetor, com variáveis de tema. `app.js`:
- `novaSessao()` chama `POST /api/sessao/nova` e guarda o id em `localStorage`.
- `enviar(pergunta)` faz `fetch('/api/chat', {method:'POST', body: JSON.stringify(...)})` e lê `response.body.getReader()` decodificando eventos SSE (`event:`/`data:`), tratando cada tipo: `texto` (append no balão, render Markdown sanitizado ao fim), `ferramenta` (linha em "Como cheguei aqui"), `processo` (preenche a aba Processo e o cabeçalho), `verificacao` (renderiza os selos; se `eh_minuta`, insere a faixa vermelha no topo do balão), `erro`, `fim` (mostra custo).
- Citações `[Doc N]` viram `<button data-doc="N">` que chama `GET /api/documento/N?sessao_id=` e mostra o texto na aba Fontes com o(s) trecho(s) citado(s) destacado(s).
- Markdown renderizado com `marked.parse` e sempre passado por `DOMPurify.sanitize`.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_estaticos.py -v`
Expected: PASS

- [ ] **Step 5: Verificação manual (registrada como passo)**

Run: `uv run uvicorn app.main:app` e abrir `http://localhost:8000`. Fazer uma pergunta real do desafio e conferir: streaming, citação clicável, selos, faixa de minuta. (Requer `.env` com chave.)

- [ ] **Step 6: Commit**

```bash
git add app/web/static/ tests/test_estaticos.py
git commit -m "feat: interface web (layout A) com streaming, citações e selos"
```

---

## Task 19: Suíte de avaliações (evals)

**Files:**
- Create: `evals/__init__.py`, `evals/casos.yaml`, `evals/rubrica.md`, `evals/executar.py`, `evals/test_smoke.py`

**Interfaces:**
- Produces: `carregar_casos(caminho='evals/casos.yaml') -> list[dict]`; `checagens_objetivas(caso, resposta, ferramentas, selos) -> dict`; `main()` que roda os casos contra o agente real e grava `evals/resultados/<data>.{md,json}`. Cada caso: `id, conversa: [pergunta...], espera: {fatos:[], ferramentas:[], selos_ok:[], selos_alerta:[]}, critico: bool`.
- `test_smoke.py` valida só a estrutura do YAML e as funções puras — não gasta API.

- [ ] **Step 1: Escrever `casos.yaml`, `rubrica.md` e o teste de smoke**

`casos.yaml` com ~25 casos (spec §9.2), incluindo os gabaritos confirmados (Joinville=190; processo sem docs `0000001-14.2023.8.99.9001`; sem magistrado `0000001-63.2025.8.99.9059`; minuta `0000001-81.2023.8.99.9011`; DV inválido `0000001-16.2022.8.99.9012`; inexistente `0009999-69.2024.8.99.9001`). `rubrica.md`: critérios do LLM-juiz (fidelidade, limites, utilidade). `evals/test_smoke.py`:
```python
from evals.executar import carregar_casos, checagens_objetivas


def test_casos_bem_formados():
    casos = carregar_casos()
    assert len(casos) >= 20
    for c in casos:
        assert c["id"] and c["conversa"] and "espera" in c
    assert any(c.get("critico") for c in casos)


def test_checagem_objetiva_fatos():
    caso = {"espera": {"fatos": ["190"], "ferramentas": ["consultar_sql"],
                       "selos_ok": [], "selos_alerta": []}}
    r = checagens_objetivas(caso, "São 190 processos.", ["consultar_sql"], [])
    assert r["fatos_ok"] is True and r["ferramentas_ok"] is True
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest evals/test_smoke.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `evals/executar.py`**

`carregar_casos` (yaml.safe_load), `checagens_objetivas` (substring dos fatos no texto; ferramentas usadas ⊇ esperadas; selos presentes por tipo/status), e `main()` que percorre os casos, chama o agente real reaproveitando `Sessao`+`responder`, coleta resposta/ferramentas/selos via `verificar`, opcionalmente chama um LLM-juiz (mesma `stream_completion` com um prompt de avaliação), e escreve os relatórios. `main()` é `asyncio.run`.

- [ ] **Step 4: Rodar e ver passar (smoke)**

Run: `uv run pytest evals/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Rodar as avaliações reais uma vez (registrado; requer chave e custo ~US$ 0,15)**

Run: `uv run python -m evals.executar`
Confere: `evals/resultados/<data>.md` gerado; casos críticos 100%.

- [ ] **Step 6: Commit**

```bash
git add evals/
git commit -m "feat: suíte de avaliações com gabaritos e checagens objetivas"
```

---

## Task 20: Observabilidade (resumo de logs) e CI

**Files:**
- Create: `scripts/resumo_logs.py`, `.github/workflows/testes.yml`, `tests/test_resumo_logs.py`

**Interfaces:**
- Produces: `resumir(caminho) -> dict` com `custo_total`, `latencia_p50`, `latencia_p95`, `contagem_selos`. CI roda `uv sync` + `uv run pytest` (sem evals, sem chave).

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_resumo_logs.py`:
```python
from scripts.resumo_logs import resumir


def test_resumo(tmp_path):
    import json
    p = tmp_path / "aud.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"custo": 0.002, "latencia": 10, "selos": [{"tipo": "citacao", "status": "ok"}]},
        {"custo": 0.003, "latencia": 20, "selos": [{"tipo": "norma", "status": "alerta"}]},
    ]) + "\n", encoding="utf-8")
    r = resumir(str(p))
    assert abs(r["custo_total"] - 0.005) < 1e-9
    assert r["contagem_selos"]["norma:alerta"] == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_resumo_logs.py -v`
Expected: FAIL

- [ ] **Step 3: Implementar `scripts/resumo_logs.py` e o workflow**

```python
import json
import statistics
from collections import Counter
from pathlib import Path


def resumir(caminho: str = "logs/auditoria.jsonl") -> dict:
    linhas = [json.loads(x) for x in Path(caminho).read_text(encoding="utf-8").splitlines() if x.strip()]
    lat = [x["latencia"] for x in linhas if x.get("latencia") is not None]
    selos = Counter(f"{s['tipo']}:{s['status']}" for x in linhas for s in x.get("selos", []))
    lat_ord = sorted(lat)
    def pct(p):
        return lat_ord[min(len(lat_ord) - 1, int(len(lat_ord) * p))] if lat_ord else 0
    return {"perguntas": len(linhas), "custo_total": round(sum(x.get("custo", 0) for x in linhas), 4),
            "latencia_p50": pct(0.5), "latencia_p95": pct(0.95), "contagem_selos": dict(selos)}


if __name__ == "__main__":
    import sys
    print(json.dumps(resumir(*(sys.argv[1:2])), ensure_ascii=False, indent=2))
```
`.github/workflows/testes.yml`:
```yaml
name: testes
on: [push, pull_request]
jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with:
          python-version: "3.12"
      - run: uv sync
      - run: uv run pytest tests -q
```
(CI roda só `tests`, não `evals`.)

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_resumo_logs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/resumo_logs.py .github/workflows/testes.yml tests/test_resumo_logs.py
git commit -m "feat: resumo de logs e CI de testes"
```

---

## Task 21: Git do projeto, hook anti-GitLab, docs finais

**Files:**
- Create: `scripts/configurar-git.sh`, `scripts/git-hooks/pre-push`, `README.md`, `DECISOES.md`, `docs/uso-de-ia.md`, `docs/roteiro-demo.md`, `CLAUDE.md`
- Move: `desafio.sqlite` → `data/desafio.sqlite`; ajustar `.gitignore`

**Interfaces:**
- Produces: repositório pronto para o GitHub, com hook que bloqueia GitLab, docs que respondem à arguição.

- [ ] **Step 1: Escrever o hook e o teste**

`scripts/git-hooks/pre-push`:
```bash
#!/usr/bin/env bash
# Bloqueia push para qualquer host GitLab.
remoto_url="$2"
if echo "$remoto_url" | grep -qi 'gitlab'; then
  echo "ERRO: push para GitLab bloqueado por política deste repositório." >&2
  exit 1
fi
exit 0
```
`tests/test_git_hook.py`:
```python
import subprocess
from pathlib import Path


def test_hook_bloqueia_gitlab():
    hook = Path("scripts/git-hooks/pre-push")
    r = subprocess.run(["bash", str(hook), "origin", "git@gitlab.exemplo.com.br:x/y.git"],
                       input="", capture_output=True, text=True)
    assert r.returncode == 1


def test_hook_permite_github():
    hook = Path("scripts/git-hooks/pre-push")
    r = subprocess.run(["bash", str(hook), "origin", "git@github.com:x/y.git"],
                       input="", capture_output=True, text=True)
    assert r.returncode == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_git_hook.py -v`
Expected: FAIL

- [ ] **Step 3: Criar o hook (com +x), `configurar-git.sh`, mover o banco**

```bash
chmod +x scripts/git-hooks/pre-push
mkdir -p data && git mv desafio.sqlite data/desafio.sqlite 2>/dev/null || mv desafio.sqlite data/desafio.sqlite
```
`scripts/configurar-git.sh` (idempotente): define `user.name`/`user.email` locais, `core.hooksPath=scripts/git-hooks`, e, se existir a chave, `core.sshCommand`. Ajustar `.gitignore` para `*.zip` e `logs/`.

- [ ] **Step 4: Escrever README.md, DECISOES.md, docs/uso-de-ia.md, docs/roteiro-demo.md, CLAUDE.md**

Conteúdo conforme a spec §10.3 e §11. O README traz: requisitos, `uv sync`, `.env`, execução (`uv run uvicorn app.main:app`), testes, avaliações, tabela de configuração, solução de problemas (IPv6/WSL2). O DECISOES.md responde às 5 perguntas da arguição com a evidência medida. O uso-de-ia.md consolida `docs/pesquisa/` e onde a IA atrapalhou.

- [ ] **Step 5: Rodar toda a suíte**

Run: `uv run pytest tests -q`
Expected: PASS (tudo verde)

- [ ] **Step 6: Configurar git e commit**

```bash
bash scripts/configurar-git.sh
git add -A
git commit -m "chore: git do projeto (hook anti-GitLab), banco em data/, docs finais"
```

- [ ] **Step 7: Verificação final antes do push (registrada)**

Rodar `uv run pytest tests -q` (verde), abrir o app e fazer o roteiro da demo. Só então criar o repositório no GitHub e `git push` (o hook garante que não vai para GitLab).

---

## Self-Review

**1. Cobertura da spec:** dados (T2–T6), agente (T7–T9), verificação (T10–T14), auditoria (T15), API+SSE (T16–T17), web (T18), evals (T19), observabilidade+CI (T20), git+docs (T21). Requisitos do desafio: entender/consultar/fundamentar/conversar/limites cobertos por T6/T9/T10–T14; minuta por T13. §8 (segurança) por T6 (SQL), T17 (documento restrito), T21 (hook). ✔

**2. Placeholders:** cada passo de código tem código real; onde há dependência de interface entre tarefas (o `_docs` do evento `ferramenta`), está explicitada em T16 passo 4. ✔

**3. Consistência de tipos:** `abrir_conexao`, `alertas_do_processo`, `obter_dossie`/`buscar_processos`/`consultar_sql`, `stream_completion` (eventos `{"tipo":...}`), `responder` (eventos de alto nível), `verificar(...) -> {"selos","eh_minuta"}` — nomes usados igualmente entre tarefas. ✔

**4. Review Focus:** pergunta sem número (T9, prompt + teste de laço), SQL em tabela base (T6 `test_sql_bloqueia_tabela_base`), documento fora da sessão (T17 `test_documento_fora_da_sessao_403`), `cost` ausente (T7 `test_custo_com_e_sem_campo`), DV do CNJ (T2 três casos). ✔

---

## Handoff de execução

Plano salvo em `docs/superpowers/plans/2026-09-24-agente-consulta-processual.md`.
