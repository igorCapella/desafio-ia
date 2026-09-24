/*
 * Núcleo da interface: só funções puras (sem DOM nem rede). O contrato (leitor SSE, citações,
 * destaques, lacunas, formatos) é testado com `node --test tests/web/nucleo.test.cjs`.
 * No navegador fica em `window.Nucleo`; no Node, em `module.exports`.
 */
(function (raiz, fabrica) {
  if (typeof module === "object" && module.exports) {
    module.exports = fabrica();
  } else {
    raiz.Nucleo = fabrica();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // ---------------------------------------------------------------- leitor SSE

  // Formato text/event-stream (WHATWG): linhas "campo: valor"; linha vazia encerra o evento.
  function criarLeitorSSE() {
    let resto = "";
    let evento = "";
    let dados = [];

    function despachar(saida) {
      if (dados.length) {
        const bruto = dados.join("\n");
        let valor;
        try {
          valor = JSON.parse(bruto);
        } catch (_) {
          valor = bruto;
        }
        saida.push({ evento: evento || "message", dados: valor });
      }
      evento = "";
      dados = [];
    }

    function processarLinha(linha, saida) {
      if (linha === "") {
        despachar(saida);
        return;
      }
      if (linha[0] === ":") return; // comentário (keepalive)
      const i = linha.indexOf(":");
      const campo = i < 0 ? linha : linha.slice(0, i);
      let valor = i < 0 ? "" : linha.slice(i + 1);
      if (valor[0] === " ") valor = valor.slice(1);
      if (campo === "event") evento = valor;
      else if (campo === "data") dados.push(valor);
    }

    return {
      alimentar(pedaco) {
        resto += pedaco;
        const saida = [];
        const rx = /\r\n|\r|\n/g;
        let inicio = 0;
        let m;
        while ((m = rx.exec(resto)) !== null) {
          // "\r" no fim pode ser a primeira metade de um "\r\n": espera o próximo pedaço.
          if (m[0] === "\r" && m.index === resto.length - 1) break;
          processarLinha(resto.slice(inicio, m.index), saida);
          inicio = m.index + m[0].length;
        }
        resto = resto.slice(inicio);
        return saida;
      },
    };
  }

  // ---------------------------------------------------------------- citações

  // [ ... ] sem colchete aninhado, ou ( ... ) sem parêntese nem colchete dentro; numa linha só.
  const RX_DELIMITADO = /\[[^\[\]\n]*\]|\([^()\[\]\n]*\)/g;
  const RX_COLCHETES = /\[[^\[\]\n]*\]/g;
  const RX_PALAVRA_MARCADOR = /^\s*(Docs?|Mov|SQL|Cadastro)(?![A-Za-zÀ-ÿ])/i;
  // Como em app/verificacao/citacoes.py: lista de ids após "Doc"/"Docs"; número seguido
  // de "/" é data, não documento.
  const RX_IDS_DOC = /\bDocs?\.?\s*(\d+(?![\d/-])(?:\s*(?:,|;|\be\b)\s*\d+(?![\d/-]))*)/gi;

  function idsDeDocumento(conteudo) {
    const ids = [];
    for (const m of conteudo.matchAll(RX_IDS_DOC)) {
      for (const n of m[1].match(/\d+/g)) {
        const id = Number(n);
        if (!ids.includes(id)) ids.push(id);
      }
    }
    return ids;
  }

  function classificarMarcador(rotulo) {
    const conteudo = rotulo.slice(1, -1);
    const chave = RX_PALAVRA_MARCADOR.exec(conteudo);
    if (!chave) return null;
    const palavra = chave[1].toLowerCase();
    const ids = idsDeDocumento(conteudo);
    // Entre parênteses só vale citação de documento, "(Doc 948)", como no verificador.
    if (rotulo[0] === "(") {
      return palavra.startsWith("doc") && ids.length ? { tipo: "doc", ids, rotulo } : null;
    }
    if (ids.length) return { tipo: "doc", ids, rotulo };
    if (palavra === "mov") return { tipo: "mov", rotulo };
    if (palavra === "sql") return { tipo: "sql", rotulo };
    if (palavra === "cadastro") return { tipo: "cadastro", rotulo };
    return null; // "[Doc n/a]": tem cara de marcador, mas não cita documento nenhum
  }

  function segmentarCitacoes(texto) {
    const segmentos = [];
    let pos = 0;
    for (const m of texto.matchAll(RX_DELIMITADO)) {
      const marcador = classificarMarcador(m[0]);
      if (!marcador) continue;
      if (m.index > pos) segmentos.push({ tipo: "texto", valor: texto.slice(pos, m.index) });
      segmentos.push(marcador);
      pos = m.index + m[0].length;
    }
    if (pos < texto.length) segmentos.push({ tipo: "texto", valor: texto.slice(pos) });
    return segmentos;
  }

  // ---------------------------------------------------------------- lacunas da minuta

  const RX_SO_RETICENCIAS = /^\[\s*(?:\.{2,}|…)\s*\]$/; // "[...]" é supressão em citação

  function segmentarLacunas(texto) {
    const segmentos = [];
    let pos = 0;
    for (const m of texto.matchAll(RX_COLCHETES)) {
      const conteudo = m[0].slice(1, -1);
      if (!conteudo.trim() || RX_PALAVRA_MARCADOR.test(conteudo) || RX_SO_RETICENCIAS.test(m[0])) {
        continue;
      }
      if (m.index > pos) segmentos.push({ tipo: "texto", valor: texto.slice(pos, m.index) });
      segmentos.push({ tipo: "lacuna", valor: m[0] });
      pos = m.index + m[0].length;
    }
    if (pos < texto.length) segmentos.push({ tipo: "texto", valor: texto.slice(pos) });
    return segmentos;
  }

  // ---------------------------------------------------------------- destaques no documento

  // Mesmo critério de app/verificacao/aspas.py: fragmento (entre reticências) com menos de
  // 15 caracteres não é conferido, então também não é destacado.
  const MIN_FRAGMENTO = 15;
  const RX_RETICENCIAS = /\[\s*(?:\.{3}|…)\s*\]|\.{3}|…/;
  const RX_PONTAS = /^[\s"'«».,;:()[\]]+|[\s"'«».,;:()[\]]+$/g;
  const RX_ESPACO = /\s/;

  // Minúsculas, espaços colapsados, sem marcação (* _ `), aspas curvas viram retas.
  // mapa[i] = posição, no texto original, do i-ésimo caractere normalizado.
  function normalizarComMapa(texto) {
    let norm = "";
    const mapa = [];
    let emEspaco = false;
    for (let i = 0; i < texto.length; i++) {
      let c = texto[i];
      if (RX_ESPACO.test(c)) {
        if (!emEspaco && norm) {
          norm += " ";
          mapa.push(i);
        }
        emEspaco = true;
        continue;
      }
      if (c === "*" || c === "_" || c === "`") continue;
      emEspaco = false;
      if (c === "“" || c === "”") c = '"';
      else if (c === "‘" || c === "’") c = "'";
      const baixa = c.toLowerCase();
      for (let k = 0; k < baixa.length; k++) {
        norm += baixa[k];
        mapa.push(i);
      }
    }
    return { norm, mapa };
  }

  function unirIntervalos(intervalos) {
    const ordenados = intervalos.slice().sort((a, b) => a.inicio - b.inicio || a.fim - b.fim);
    const unidos = [];
    for (const atual of ordenados) {
      const ultimo = unidos[unidos.length - 1];
      if (ultimo && atual.inicio <= ultimo.fim) ultimo.fim = Math.max(ultimo.fim, atual.fim);
      else unidos.push({ inicio: atual.inicio, fim: atual.fim });
    }
    return unidos;
  }

  function trechosParaDestacar(textoDoDocumento, trechos) {
    const { norm, mapa } = normalizarComMapa(String(textoDoDocumento || ""));
    const intervalos = [];
    for (const trecho of trechos || []) {
      const partes = String(trecho).split(RX_RETICENCIAS);
      for (const parte of partes) {
        const frag = normalizarComMapa(parte).norm.replace(RX_PONTAS, "");
        if (!frag || (partes.length > 1 && frag.length < MIN_FRAGMENTO)) continue;
        const i = norm.indexOf(frag);
        if (i >= 0) intervalos.push({ inicio: mapa[i], fim: mapa[i + frag.length - 1] + 1 });
      }
    }
    return unirIntervalos(intervalos);
  }

  // Primeira linha igual ao aviso da faixa (ignorando pontuação e marcação): como a faixa já
  // mostra o aviso, a linha sai da exibição e da cópia. Qualquer outra diferença mantém o texto.
  function semAvisoRepetido(texto, aviso) {
    const normalizar = (s) => String(s || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    const alvo = normalizar(aviso);
    const m = /^\s*([^\n]*)(?:\n|$)/.exec(String(texto || ""));
    if (!alvo || !m || normalizar(m[1]) !== alvo) return texto;
    return texto.slice(m[0].length).replace(/^(?:[ \t]*\n)+/, "");
  }

  // ---------------------------------------------------------------- formatos brasileiros

  function ausente(valor) {
    return valor === null || valor === undefined || valor === "" || Number.isNaN(Number(valor));
  }

  function formatarDecimal(valor, casas) {
    const [inteiro, decimal] = Math.abs(valor).toFixed(casas).split(".");
    const agrupado = inteiro.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (valor < 0 ? "-" : "") + agrupado + (decimal ? "," + decimal : "");
  }

  function formatarBRL(valor) {
    if (ausente(valor)) return "—";
    const n = Number(valor);
    return (n < 0 ? "-" : "") + "R$ " + formatarDecimal(Math.abs(n), 2);
  }

  function formatarCusto(usd, casas = 4) {
    if (ausente(usd)) return "—";
    return "US$ " + formatarDecimal(Number(usd), casas);
  }

  function formatarNumero(valor) {
    return ausente(valor) ? "—" : formatarDecimal(Math.round(Number(valor)), 0);
  }

  // "2024-08-26" (ou "2024-08-26T10:00") → "26/08/2024"; outro formato volta como veio.
  function formatarData(iso) {
    if (!iso) return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    return m ? `${m[3]}/${m[2]}/${m[1]}` : String(iso);
  }

  function formatarDuracao(ms) {
    if (ausente(ms)) return "—";
    const n = Number(ms);
    if (n < 1000) return formatarDecimal(n, n < 10 ? 1 : 0) + " ms";
    const s = n / 1000;
    return formatarDecimal(s, s < 10 ? 1 : 0) + " s";
  }

  return {
    criarLeitorSSE,
    segmentarCitacoes,
    segmentarLacunas,
    trechosParaDestacar,
    semAvisoRepetido,
    formatarBRL,
    formatarCusto,
    formatarNumero,
    formatarData,
    formatarDuracao,
  };
});
