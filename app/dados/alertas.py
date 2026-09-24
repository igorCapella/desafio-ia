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
