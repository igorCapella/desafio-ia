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
