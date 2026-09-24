const test = require("node:test");
const assert = require("node:assert/strict");
const N = require("../../app/web/static/nucleo.js");

test("leitor SSE junta pedaços, ignora comentários e decodifica JSON", () => {
  const leitor = N.criarLeitorSSE();
  assert.deepEqual(leitor.alimentar('event: texto\ndata: {"delta": "Ol'), []);
  const eventos = leitor.alimentar('á"}\n\n: ping\n\nevent: fim\r\ndata: {"uso": {}}\r\n\r\n');
  assert.deepEqual(eventos, [{ evento: "texto", dados: { delta: "Olá" } },
                             { evento: "fim", dados: { uso: {} } }]);
});

test("citações viram segmentos, inclusive várias no mesmo marcador", () => {
  const texto = "Ver [Doc 93 – Sentença, 26/08/2024] e [Doc 86, 90]; " +
                "[Mov 30/09/2024 – Trânsito em Julgado] [SQL] [Cadastro].";
  const s = N.segmentarCitacoes(texto);
  assert.deepEqual(s.map((x) => x.tipo), ["texto", "doc", "texto", "doc", "texto", "mov", "texto",
                                          "sql", "texto", "cadastro", "texto"]);
  assert.deepEqual(s.filter((x) => x.tipo === "doc").map((x) => x.ids), [[93], [86, 90]]);
  assert.equal(s.map((x) => (x.tipo === "texto" ? x.valor : x.rotulo)).join(""), texto);
});

test("número seguido de barra é data, não documento; plural também conta", () => {
  const s = N.segmentarCitacoes("[Doc 86, 24/10/2022] e [Docs 86 e 91]");
  assert.deepEqual(s.filter((x) => x.tipo === "doc").map((x) => x.ids), [[86], [86, 91]]);
});

test("destaca trechos no texto original, ignorando caixa, espaços e aspas", () => {
  const doc = "A parte autora  não se desincumbiu\ndo ônus de comprovar. Julgo IMPROCEDENTE o pedido.";
  const r = N.trechosParaDestacar(doc, ["não se desincumbiu do ônus", "“julgo improcedente”"]);
  assert.deepEqual(r.map((x) => doc.slice(x.inicio, x.fim)), ["não se desincumbiu\ndo ônus",
                                                              "Julgo IMPROCEDENTE"]);
});

test("reticências localizam cada fragmento separadamente", () => {
  const doc = "Primeira parte do texto. Meio irrelevante. Segunda parte do texto final.";
  const r = N.trechosParaDestacar(doc, ["Primeira parte do texto … Segunda parte do texto final"]);
  assert.deepEqual(r.map((x) => doc.slice(x.inicio, x.fim)), ["Primeira parte do texto",
                                                              "Segunda parte do texto final"]);
});

test("lacunas de decisão da minuta", () => {
  const s = N.segmentarLacunas("Ante o exposto, [JULGO PROCEDENTE / IMPROCEDENTE] o pedido " +
                               "[Doc 86 – Petição Inicial] no valor de [R$ ...].");
  assert.deepEqual(s.filter((x) => x.tipo === "lacuna").map((x) => x.valor),
                   ["[JULGO PROCEDENTE / IMPROCEDENTE]", "[R$ ...]"]);
});

test("formatos brasileiros", () => {
  assert.equal(N.formatarBRL(11166.69), "R$ 11.166,69");
  assert.equal(N.formatarBRL(null), "—");
  assert.equal(N.formatarCusto(0.0017333), "US$ 0,0017");
});

test("data ISO não vira documento e cada Doc do marcador conta", () => {
  const s = N.segmentarCitacoes("[Doc 939, 2023-06-01; Doc 944, 2024-10-08]");
  assert.deepEqual(s.filter((x) => x.tipo === "doc").map((x) => x.ids), [[939, 944]]);
});
