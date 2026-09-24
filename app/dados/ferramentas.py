from contextlib import closing
import re
import sqlite3
import time

from app.dados.alertas import alertas_do_processo
from app.dados.conexao import VISOES, abrir_conexao, abrir_conexao_consulta
from app.dados.numero_cnj import normalizar_numero

_POLO_ATIVO = {"Petição Inicial", "Emenda à Inicial", "Réplica"}
_POLO_PASSIVO = {"Contestação", "Exceção de Pré-Executividade", "Embargos à Execução Fiscal"}
_LISTA_VISOES = ", ".join(VISOES)
_TIMEOUT_S = 5.0
_MAX_CELULA = 4_000       # o maior texto de documento no banco tem 2.589 caracteres
_MAX_RESULTADO = 60_000   # soma de caracteres das células devolvidas ao modelo


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
    if conn is None:
        with closing(abrir_conexao()) as propria:
            return obter_dossie(numero, propria)
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
        ref = f"Doc {d['id']} – {d['tipo']}"
        if d["oab"] and d["advogado"]:
            adv = advogados.setdefault((d["advogado"], d["oab"]), {
                "nome": d["advogado"], "oab": d["oab"], "documentos": [],
                "base_inferencia": [], "_polos": set()})
            adv["documentos"].append(ref)
            if polo := _polo_inferido(d["tipo"]):
                adv["_polos"].add(polo)
                adv["base_inferencia"].append(ref)
        elif "Ministério Público" in (d["tipo"] or "") or "Promotor" in (d["autor"] or ""):
            ministerio.append({"documento": ref, "autor": d["autor"]})
    for adv in advogados.values():
        # Inferência pelo tipo dos documentos que o advogado assina (spec §4.6).
        polos = adv.pop("_polos")
        adv["polo_inferido"] = (polos.pop() if len(polos) == 1
                                else "conflitante" if polos else "não inferido")
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
                     assunto=None, comarca=None, situacao=None,
                     cpfs_do_usuario: frozenset[str] = frozenset()) -> dict:
    # cpfs_do_usuario: CPFs (só dígitos) que o próprio usuário digitou na conversa.
    # Quem preenche é o laço do agente, nunca o modelo (não está em DEFINICOES_TOOLS).
    if conn is None:
        with closing(abrir_conexao()) as propria:
            return buscar_processos(propria, parte, cpf_cnpj, classe, assunto,
                                    comarca, situacao, cpfs_do_usuario)
    cond, args = [], []
    if parte:
        cond.append("id in (select processo_id from v_partes "
                    "where instr(normalizar(nome), normalizar(?)) > 0)")
        args.append(parte)
    if cpf_cnpj:
        digitos = re.sub(r"\D", "", str(cpf_cnpj))
        if len(digitos) not in (11, 14):
            return {"erro": "Informe o CPF (11 dígitos) ou o CNPJ (14 dígitos) completo."}
        if len(digitos) == 11 and digitos not in cpfs_do_usuario:
            # O CPF aparece mascarado (***.xxx.xxx-**); aceitar qualquer CPF faria desta
            # busca um oráculo para descobrir os dígitos ocultos por tentativa.
            return {"erro": "Por proteção de dados, a busca por CPF só aceita um número "
                            "digitado pelo usuário nesta conversa."}
        # Compara com o documento cru porque v_partes pode estar mascarada;
        # o documento nunca volta na resposta.
        cond.append("id in (select pp.processo_id from processo_parte pp "
                    "join parte pa on pa.id = pp.parte_id where "
                    "replace(replace(replace(pa.documento, '.', ''), '-', ''), '/', '') = ?)")
        args.append(digitos)
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


def _erro_sql(e: Exception) -> str:
    if isinstance(e, MemoryError):
        return "Resultado grande demais para a memória; agregue ou limite a consulta."
    msg = str(e)
    if isinstance(e, sqlite3.ProgrammingError) and "one statement" in msg:
        return "Envie um único comando SQL por vez."
    if "interrupted" in msg:
        return "Consulta interrompida por passar de 5 s; restrinja os filtros ou agregue."
    if "too big" in msg or "too long" in msg or "too large" in msg:
        return ("Valor ou comando grande demais (limite de 1 MB por célula); agregue menos "
                "ou use obter_dossie para a íntegra de um processo.")
    if "not authorized" in msg or "prohibited" in msg:
        return f"Comando não permitido: apenas SELECT (leitura) nas visões {_LISTA_VISOES}."
    if "no such table" in msg:
        return f"Tabela inexistente ({msg}); as consultas só enxergam as visões {_LISTA_VISOES}."
    return f"Erro de SQL: {msg}"


def _celula(v):
    if isinstance(v, bytes):
        return f"<blob de {len(v)} bytes>"
    if isinstance(v, str) and len(v) > _MAX_CELULA:
        return v[:_MAX_CELULA] + f" ... [cortado: {len(v)} caracteres no total]"
    return v


def consultar_sql(sql: str) -> dict:
    if not isinstance(sql, str) or not sql.strip():
        return {"sql": sql, "erro": "Informe um comando SQL (texto)."}
    conn = abrir_conexao_consulta()
    inicio = time.monotonic()
    limite = inicio + _TIMEOUT_S
    conn.set_progress_handler(lambda: int(time.monotonic() > limite), 10_000)
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(51)
        cols = [d[0] for d in cur.description or []]
        linhas, tamanho = [], 0
        for r in rows[:50]:
            linha = [_celula(v) for v in r]
            tamanho += sum(len(str(v)) for v in linha)
            if linhas and tamanho > _MAX_RESULTADO:
                break
            linhas.append(linha)
        return {"sql": sql, "colunas": cols, "linhas": linhas,
                "truncado": len(rows) > len(linhas),
                "duracao_ms": round((time.monotonic() - inicio) * 1000, 1)}
    except (sqlite3.Error, MemoryError) as e:
        return {"sql": sql, "erro": _erro_sql(e)}
    finally:
        conn.close()


DEFINICOES_TOOLS = [
    {"type": "function", "function": {
        "name": "obter_dossie",
        "description": "Dossiê completo de um processo: cadastro, partes por polo, advogados "
                       "identificados (polo inferido pelo tipo de documento), Ministério Público, "
                       "movimentações e íntegra dos documentos (com id para citação), além de "
                       "alertas de qualidade dos dados.",
        "parameters": {"type": "object", "properties": {
            "numero": {"type": "string", "description": "Número CNJ, com ou sem pontuação."}},
            "required": ["numero"]}}},
    {"type": "function", "function": {
        "name": "buscar_processos",
        "description": "Localiza processos por parte (nome, busca parcial), CPF/CNPJ completo, "
                       "classe, assunto, comarca ou situação (ao menos um filtro). Retorna até 20 "
                       "resultados e o total encontrado.",
        "parameters": {"type": "object", "properties": {
            "parte": {"type": "string"}, "cpf_cnpj": {"type": "string"},
            "classe": {"type": "string"}, "assunto": {"type": "string"},
            "comarca": {"type": "string"}, "situacao": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "consultar_sql",
        "description": "Executa UMA consulta SQL SELECT (somente leitura). As únicas tabelas "
                       "existentes são as visões v_processo, v_partes, v_documentos, "
                       "v_movimentacoes, v_magistrados e v_unidades (CPF mascarado). A função "
                       "normalizar(texto) compara sem acento e sem caixa. Até 50 linhas.",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string"}}, "required": ["sql"]}}},
]

IMPL = {"obter_dossie": obter_dossie, "buscar_processos": buscar_processos,
        "consultar_sql": consultar_sql}
