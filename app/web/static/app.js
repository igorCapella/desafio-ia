/*
 * Interface do agente: DOM e ligação com a API (/api/chat em SSE, /api/documento,
 * /api/sessao/nova, /api/saude). As regras puras ficam em nucleo.js (window.Nucleo).
 * Texto vindo de fora (modelo, documentos, cadastro) entra só por textContent/createElement;
 * a única exceção é o Markdown da resposta, sempre sanitizado pelo DOMPurify.
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  if (!window.Nucleo || !window.marked || !window.DOMPurify) {
    const falha = document.createElement("p");
    falha.className = "aviso-sistema";
    falha.textContent = "Falha ao carregar os scripts da interface. Recarregue a página.";
    $("mensagens").replaceChildren(falha);
    return;
  }

  const N = window.Nucleo;
  const CHAVES = { sessao: "consulta.sessao", conversa: "consulta.conversa", tema: "consulta.tema" };
  const RX_ID_SESSAO = /^[0-9a-f]{32}$/;
  const AVISO_PADRAO = "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA PROFERIDA";
  const COMPLEMENTO_FAIXA = "Requer revisão e assinatura do magistrado.";
  const ROTULO_COPIAR = "Copiar minuta (com aviso)";
  const ABAS = ["fontes", "como", "processo"];
  const FASES = { pensando: "pensando…", escrevendo: "escrevendo…", verificando: "verificando…" };
  const TITULOS_FONTE = {
    mov: "Ver na linha do tempo (aba Processo)",
    cadastro: "Ver a ficha do processo (aba Processo)",
    sql: "Ver a consulta exata (aba Como cheguei aqui)",
  };
  const POLOS = {
    ativo: "polo ativo",
    passivo: "polo passivo",
    conflitante: "polo conflitante (assina peças dos dois polos)",
  };

  // Só as marcas que o Markdown gera: sem imagem, estilo, classe ou id. Assim nada de fora é
  // carregado e a resposta do modelo não consegue imitar a faixa nem os selos da interface.
  const OPCOES_PURIFY = {
    ALLOWED_TAGS: ["a", "b", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4",
                   "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "s", "strong", "sub", "sup",
                   "table", "tbody", "td", "th", "thead", "tr", "ul"],
    ALLOWED_ATTR: ["href", "title", "start", "colspan", "rowspan", "align"],
    ALLOW_DATA_ATTR: false,
  };
  const OPCOES_MARKED = { gfm: true, breaks: true };
  const escaparHtml = (texto) => String(texto).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  // HTML cru escrito pelo modelo aparece como texto: a resposta é Markdown, e uma injeção vinda
  // de documento fica visível em vez de virar marcação. O DOMPurify segue como segunda barreira.
  marked.use({
    renderer: { html: ({ text, block }) => (block ? `<p>${escaparHtml(text)}</p>` : escaparHtml(text)) },
  });

  DOMPurify.addHook("afterSanitizeAttributes", (no) => {
    if (no.tagName === "A") {  // link da resposta nunca troca a página da demonstração
      no.setAttribute("target", "_blank");
      no.setAttribute("rel", "noopener noreferrer");
    }
  });

  const el = {
    raiz: document.documentElement,
    mensagens: $("mensagens"),
    boasVindas: $("boas-vindas"),
    formulario: $("formulario"),
    pergunta: $("pergunta"),
    enviar: $("botao-enviar"),
    nova: $("botao-nova"),
    tema: $("botao-tema"),
    iconeTema: $("icone-tema"),
    focoNumero: $("foco-numero"),
    focoClasse: $("foco-classe"),
    focoSituacao: $("foco-situacao"),
    painel: $("painel"),
    painelFontes: $("painel-fontes"),
    painelProcesso: $("painel-processo"),
    fontesDocumento: $("fontes-documento"),
    fontesLista: $("fontes-lista"),
    fontesItens: $("fontes-itens"),
    comoConteudo: $("como-conteudo"),
    comoCusto: $("como-custo"),
    processoConteudo: $("processo-conteudo"),
  };

  const estado = {
    sessaoId: null,
    conversa: 0,               // muda a cada "Nova conversa": respostas antigas param de mexer na tela
    emAndamento: null,         // { resp, controle }
    ficha: null,
    metaDocs: new Map(),       // id → metadados do documento (das fichas recebidas)
    docs: new Map(),           // cache de /api/documento desta conversa
    trechosPorDoc: new Map(),  // id → Set de trechos literais conferidos (selo de aspas)
    fontesCitadas: [],         // ids citados, os da resposta mais recente primeiro
    docAberto: null,
    pedidoDoc: 0,
    perguntas: 0,
    custoSessao: 0,
    saude: null,
  };

  // ---------------------------------------------------------------- utilidades

  function criar(tag, classe, texto) {
    const no = document.createElement(tag);
    if (classe) no.className = classe;
    if (texto !== undefined && texto !== null) no.textContent = String(texto);
    return no;
  }

  function botao(classe, texto) {
    const b = criar("button", classe, texto);
    b.type = "button";
    return b;
  }

  // Armazenamento local pode estar bloqueado (janela privada, política do navegador).
  function lerLocal(chave) {
    try {
      return localStorage.getItem(chave);
    } catch (_) {
      return null;
    }
  }

  function gravarLocal(chave, valor) {
    try {
      if (valor === null) localStorage.removeItem(chave);
      else localStorage.setItem(chave, valor);
    } catch (_) {
      /* segue sem persistir */
    }
  }

  const plural = (n, um, varios) => `${N.formatarNumero(n)} ${n === 1 ? um : varios}`;
  const juntar = (...valores) => valores.filter(Boolean).join(" · ") || "—";
  const semPonto = (texto) => String(texto || "").replace(/\.\s*$/, "");
  const suave = () => (matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");
  const telaEstreita = () => matchMedia("(max-width: 960px)").matches;

  function listaChaveValor(pares) {
    const dl = criar("dl", "kv");
    for (const [chave, valor] of pares) {
      const dd = criar("dd");
      dd.append(valor);
      dl.append(criar("dt", null, chave), dd);
    }
    return dl;
  }

  function avisoSistema(mensagem) {
    el.mensagens.append(criar("p", "aviso-sistema", mensagem));
  }

  // ---------------------------------------------------------------- tema

  const temaSalvo = lerLocal(CHAVES.tema);
  if (temaSalvo === "claro" || temaSalvo === "escuro") el.raiz.dataset.tema = temaSalvo;

  function temaEfetivo() {
    if (el.raiz.dataset.tema) return el.raiz.dataset.tema;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro";
  }

  function atualizarBotaoTema() {
    const escuro = temaEfetivo() === "escuro";
    el.iconeTema.textContent = escuro ? "☀" : "☾";
    el.tema.setAttribute("aria-label", escuro ? "Usar tema claro" : "Usar tema escuro");
  }

  function alternarTema() {
    const novo = temaEfetivo() === "escuro" ? "claro" : "escuro";
    el.raiz.dataset.tema = novo;
    gravarLocal(CHAVES.tema, novo);
    atualizarBotaoTema();
  }

  // ---------------------------------------------------------------- abas do painel

  function abaAtiva() {
    return ABAS.find((a) => $(`aba-${a}`).getAttribute("aria-selected") === "true");
  }

  function mostrarAba(nome, { focar = false } = {}) {
    for (const a of ABAS) {
      const aba = $(`aba-${a}`);
      const ativa = a === nome;
      aba.setAttribute("aria-selected", String(ativa));
      aba.tabIndex = ativa ? 0 : -1;
      $(`painel-${a}`).hidden = !ativa;
      if (ativa) {
        aba.classList.remove("novidade");
        if (focar) aba.focus();
      }
    }
  }

  function teclaNasAbas(evento) {
    const i = ABAS.indexOf(abaAtiva());
    const destino = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: ABAS.length - 1 }[evento.key];
    if (destino === undefined) return;
    evento.preventDefault();
    mostrarAba(ABAS[(destino + ABAS.length) % ABAS.length], { focar: true });
  }

  // Em tela estreita o painel fica abaixo do chat: leva a pessoa até ele.
  function trazerPainelParaVista() {
    if (telaEstreita()) el.painel.scrollIntoView({ behavior: suave(), block: "start" });
  }

  // ---------------------------------------------------------------- API

  async function pedirJSON(url, opcoes) {
    const r = await fetch(url, opcoes);
    if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
    return r.json();
  }

  async function novaSessao() {
    const { sessao_id: id } = await pedirJSON("/api/sessao/nova", { method: "POST" });
    estado.sessaoId = id;
    gravarLocal(CHAVES.sessao, id);
    return id;
  }

  function garantirSessao() {
    return estado.sessaoId ? Promise.resolve(estado.sessaoId) : novaSessao();
  }

  async function atualizarSaude() {
    try {
      estado.saude = await pedirJSON("/api/saude");
    } catch (_) {
      estado.saude = null;
    }
    renderizarCusto();
  }

  async function obterDocumento(id) {
    if (estado.docs.has(id)) return estado.docs.get(id);
    const sessaoId = await garantirSessao();
    const doc = await pedirJSON(`/api/documento/${encodeURIComponent(id)}` +
                                `?sessao_id=${encodeURIComponent(sessaoId)}`);
    if (sessaoId === estado.sessaoId) estado.docs.set(id, doc);
    return doc;
  }

  // fetch POST + leitura do corpo em pedaços; o Nucleo junta eventos partidos entre pedaços.
  async function lerEventos(resposta, aoEvento) {
    const leitor = resposta.body.getReader();
    const decodificador = new TextDecoder();
    const sse = N.criarLeitorSSE();
    for (;;) {
      const { value, done } = await leitor.read();
      if (done) break;
      sse.alimentar(decodificador.decode(value, { stream: true })).forEach(aoEvento);
    }
    sse.alimentar(decodificador.decode()).forEach(aoEvento);
  }

  // ---------------------------------------------------------------- envio da pergunta

  async function enviar(textoDigitado) {
    const pergunta = textoDigitado.trim();
    if (!pergunta || estado.emAndamento) return;
    let sessaoId;
    try {
      sessaoId = await garantirSessao();
    } catch (_) {
      avisoSistema("Sem conexão com o servidor: não foi possível abrir a conversa.");
      return;
    }
    const resp = criarResposta(pergunta);
    const controle = new AbortController();
    estado.emAndamento = { resp, controle };
    estado.perguntas += 1;
    salvarConversa();
    el.pergunta.value = "";
    ajustarAltura();
    modoEnvio(true);
    iniciarPainelComo(resp);
    renderizarCusto();
    try {
      const resposta = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ sessao_id: sessaoId, pergunta }),
        signal: controle.signal,
      });
      if (!resposta.ok || !resposta.body) {
        throw Object.assign(new Error(`HTTP ${resposta.status}`), { status: resposta.status });
      }
      await lerEventos(resposta, (ev) => tratarEvento(resp, ev));
    } catch (erro) {
      if (resp.conversa === estado.conversa) aoErro(resp, { mensagem: mensagemDeFalha(erro, resp) });
    } finally {
      finalizar(resp);
    }
  }

  function mensagemDeFalha(erro, resp) {
    if (erro.name === "AbortError") return "Resposta interrompida.";
    if (erro.status === 422) return "A pergunta precisa ter entre 1 e 4.000 caracteres.";
    if (erro.status) return `O servidor respondeu com erro (HTTP ${erro.status}). Tente de novo.`;
    return resp.texto
      ? "A conexão caiu no meio da resposta; o texto recebido até aqui foi mantido."
      : "Sem conexão com o servidor. Confira se ele está no ar e tente de novo.";
  }

  function modoEnvio(ativo) {
    el.enviar.textContent = ativo ? "Parar" : "Enviar";
    el.enviar.classList.toggle("parar", ativo);
    el.enviar.setAttribute("aria-label", ativo ? "Parar a resposta" : "Enviar pergunta");
  }

  function ajustarAltura() {
    const t = el.pergunta;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight + 2, Math.round(window.innerHeight * 0.3))}px`;
  }

  // ---------------------------------------------------------------- eventos SSE

  const TRATADORES = {
    status: aoStatus,
    ferramenta: aoFerramenta,
    texto: aoTexto,
    processo: aoProcesso,
    erro: aoErro,
    verificacao: aoVerificacao,
    fim: aoFim,
  };

  function tratarEvento(resp, { evento, dados }) {
    const tratar = TRATADORES[evento];
    if (!tratar || !dados || typeof dados !== "object" || resp.conversa !== estado.conversa) return;
    try {
      tratar(resp, dados);
    } catch (erro) {
      // Falha ao desenhar um evento não pode derrubar o resto da resposta.
      console.error(`Falha ao tratar o evento "${evento}":`, erro);
    }
  }

  function aoStatus(resp, { fase, ferramenta }) {
    if (fase === "consultando") {
      resp.separar = Boolean(resp.texto);
      resp.el.fase.textContent = `consultando ${ferramenta || "o banco"}…`;
    } else {
      resp.el.fase.textContent = FASES[fase] || `${fase}…`;
    }
  }

  function aoTexto(resp, { delta }) {
    if (typeof delta !== "string") return;
    // Texto escrito antes de uma consulta e texto depois dela viram parágrafos separados.
    if (resp.separar && resp.texto && !resp.texto.endsWith("\n")) resp.texto += "\n\n";
    resp.separar = false;
    resp.texto += delta;
    resp.el.balao.hidden = false;
    agendarRender(resp);
  }

  function aoFerramenta(resp, ev) {
    comRolagem(() => {
      resp.el.passos.append(criar("li", null, `⚙ ${chamadaResumida(ev)} → ${ev.resumo || "—"} · ` +
                                              N.formatarDuracao(ev.duracao_ms)));
      resp.el.passos.hidden = false;
    });
    adicionarPassoFerramenta(resp, ev);
  }

  function aoProcesso(resp, ficha) {
    if (!ficha.numero) return;
    definirFicha(ficha);
    if (abaAtiva() !== "processo") $("aba-processo").classList.add("novidade");
  }

  function aoErro(resp, { mensagem }) {
    resp.erros += 1;
    comRolagem(() => {
      resp.el.balao.hidden = false;
      resp.el.balao.append(criar("p", "erro-resposta", `⚠ ${mensagem || "Erro inesperado."}`));
    });
  }

  function aoVerificacao(resp, ver) {
    resp.verificada = true;
    resp.selos = Array.isArray(ver.selos) ? ver.selos : [];
    registrarTrechos(resp.selos);
    comRolagem(() => {
      renderizarSelos(resp);
      if (ver.eh_minuta) aplicarMinuta(resp, ver.aviso || AVISO_PADRAO);
    });
    preencherVerificacaoPainel(resp);
    redesenharDocumentoAberto();
  }

  function aoFim(resp, { uso, custo_sessao: custoSessao }) {
    resp.uso = uso || {};
    if (typeof custoSessao === "number") estado.custoSessao = custoSessao;
    salvarConversa();
    preencherRespostaPainel(resp);
    atualizarSaude();  // custo acumulado × teto, atualizado após cada resposta
  }

  function finalizar(resp) {
    if (estado.emAndamento && estado.emAndamento.resp === resp) estado.emAndamento = null;
    if (resp.conversa !== estado.conversa) return;
    resp.el.fase.remove();
    resp.el.artigo.setAttribute("aria-busy", "false");
    // Sem o evento de verificação (conexão perdida), a faixa ainda sai se o texto é minuta.
    if (!resp.verificada && /proposta de texto gerada por ia/i.test(resp.texto)) {
      aplicarMinuta(resp, AVISO_PADRAO);
    }
    if (!resp.texto && !resp.erros) aoErro(resp, { mensagem: "O agente não devolveu texto nesta resposta." });
    if (resp.texto) comRolagem(() => renderizarConteudo(resp));
    const ids = N.segmentarCitacoes(resp.texto).filter((s) => s.tipo === "doc").flatMap((s) => s.ids);
    if (ids.length) atualizarListaFontes([...new Set(ids)]);
    if (!resp.uso) preencherRespostaPainel(resp);
    modoEnvio(false);
  }

  // ---------------------------------------------------------------- chat

  function pertoDoFim() {
    const m = el.mensagens;
    return m.scrollHeight - m.scrollTop - m.clientHeight < 120;
  }

  // Acompanha o texto novo só se a pessoa não rolou para cima para ler.
  function comRolagem(acao) {
    const colado = pertoDoFim();
    acao();
    if (colado) el.mensagens.scrollTop = el.mensagens.scrollHeight;
  }

  function criarResposta(pergunta) {
    el.boasVindas.hidden = true;
    const artigo = criar("article", "resposta");
    artigo.setAttribute("aria-label", "Resposta do agente");
    artigo.setAttribute("aria-busy", "true");
    const passos = criar("ol", "passos");
    passos.setAttribute("aria-label", "Consultas feitas");
    passos.hidden = true;
    const conteudo = criar("div", "conteudo");
    const balao = criar("div", "balao");
    balao.hidden = true;
    balao.append(conteudo);
    const fase = criar("p", "fase", FASES.pensando);
    const selos = criar("div", "selos");
    selos.setAttribute("aria-label", "Verificação da resposta");
    selos.hidden = true;
    const acoes = criar("div", "acoes");
    acoes.hidden = true;
    artigo.append(passos, balao, fase, selos, acoes);
    el.mensagens.append(criar("p", "msg-usuario", pergunta), artigo);
    el.mensagens.scrollTop = el.mensagens.scrollHeight;
    return {
      conversa: estado.conversa, pergunta, texto: "", separar: false, agendado: false,
      ehMinuta: false, aviso: null, verificada: false, selos: [], erros: 0, uso: null,
      painel: null, el: { artigo, passos, balao, conteudo, fase, selos, acoes },
    };
  }

  function agendarRender(resp) {
    if (resp.agendado) return;
    resp.agendado = true;
    requestAnimationFrame(() => {
      resp.agendado = false;
      if (resp.conversa === estado.conversa) comRolagem(() => renderizarConteudo(resp));
    });
  }

  function textoExibido(resp) {
    return resp.ehMinuta ? N.semAvisoRepetido(resp.texto, resp.aviso) : resp.texto;
  }

  function renderizarConteudo(resp) {
    const html = marked.parse(textoExibido(resp), OPCOES_MARKED);
    resp.el.conteudo.innerHTML = DOMPurify.sanitize(html, OPCOES_PURIFY);
    decorarTexto(resp.el.conteudo, resp.ehMinuta);
  }

  function chamadaResumida({ nome, args }) {
    const valores = Object.entries(args || {})
      .filter(([chave]) => chave !== "sql")  // o SQL exato fica na aba "Como cheguei aqui"
      .map(([chave, valor]) => (nome === "obter_dossie" ? String(valor) : `${chave}: ${valor}`));
    return valores.length ? `${nome}(${valores.join(", ")})` : nome;
  }

  // ---------------------------------------------------------------- citações e lacunas

  // Troca marcadores por chips nos NÓS DE TEXTO do HTML já sanitizado (nunca no HTML cru).
  function decorarTexto(raiz, minuta) {
    const percurso = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT);
    const nos = [];
    while (percurso.nextNode()) {
      const no = percurso.currentNode;
      if (/[[(]/.test(no.data) && !no.parentElement.closest("code, pre, a")) nos.push(no);
    }
    for (const no of nos) no.replaceWith(fragmentoDecorado(no.data, minuta));
  }

  function fragmentoDecorado(texto, minuta) {
    const frag = document.createDocumentFragment();
    for (const seg of N.segmentarCitacoes(texto)) {
      frag.append(seg.tipo === "texto" ? textoComLacunas(seg.valor, minuta) : chipsDoMarcador(seg));
    }
    return frag;
  }

  function textoComLacunas(texto, minuta) {
    const frag = document.createDocumentFragment();
    for (const seg of N.segmentarLacunas(texto)) {
      if (seg.tipo === "texto") {
        frag.append(seg.valor);
      } else if (/^\[\s*verificar\s*\]$/i.test(seg.valor)) {
        frag.append(criar("mark", "marca-verificar", seg.valor));  // norma fora dos autos
      } else if (minuta) {
        const lacuna = criar("mark", "lacuna", seg.valor);
        if (/procedente|julgo/i.test(seg.valor)) lacuna.classList.add("decisao");
        lacuna.title = "Campo a preencher pelo magistrado";
        frag.append(lacuna);
      } else {
        frag.append(seg.valor);
      }
    }
    return frag;
  }

  function botaoDoc(id, rotulo) {
    const b = botao("cite cite-doc", rotulo);
    b.dataset.doc = String(id);
    b.title = `Abrir o Doc ${id} na aba Fontes`;
    return b;
  }

  function chipsDoMarcador(seg) {
    const semDelimitador = seg.rotulo.slice(1, -1).trim();
    if (seg.tipo !== "doc") {
      const b = botao(`cite cite-${seg.tipo}`, semDelimitador);
      b.dataset.fonte = seg.tipo;
      b.dataset.rotulo = seg.rotulo;
      b.title = TITULOS_FONTE[seg.tipo];
      return b;
    }
    if (seg.ids.length === 1) return botaoDoc(seg.ids[0], semDelimitador);
    const frag = document.createDocumentFragment();
    seg.ids.forEach((id, i) => {
      if (i) frag.append(" ");
      frag.append(botaoDoc(id, rotuloDoc(id)));
    });
    return frag;
  }

  // "Doc 86 – Petição Inicial" (advogados, Ministério Público) vira chip clicável.
  function chipReferencia(referencia) {
    const m = /\bDoc\.?\s*(\d+)/i.exec(String(referencia));
    return m ? botaoDoc(Number(m[1]), String(referencia)) : document.createTextNode(String(referencia));
  }

  function rotuloDoc(id, { comData = false } = {}) {
    const meta = estado.metaDocs.get(id);
    if (!meta) return `Doc ${id}`;
    const base = `Doc ${id} – ${meta.tipo}`;
    return comData && meta.data_juntada ? `${base} · ${N.formatarData(meta.data_juntada)}` : base;
  }

  function aoClicarFonte(evento) {
    const alvo = evento.target.closest("[data-doc], [data-fonte]");
    if (!alvo) return;
    if (alvo.dataset.doc) abrirDocumento(Number(alvo.dataset.doc), alvo.dataset.trecho);
    else irParaFonte(alvo.dataset.fonte, alvo.dataset.rotulo || "");
  }

  function irParaFonte(tipo, rotulo) {
    if (tipo === "sql") {
      mostrarAba("como");
      trazerPainelParaVista();
      const sql = el.comoConteudo.querySelector("pre.sql");
      if (sql) realcar(sql);
      return;
    }
    mostrarAba("processo");
    trazerPainelParaVista();
    const datas = [...rotulo.matchAll(/(\d{2})\/(\d{2})\/(\d{4})|(\d{4})-(\d{2})-(\d{2})/g)]
      .map((m) => (m[1] ? `${m[3]}-${m[2]}-${m[1]}` : `${m[4]}-${m[5]}-${m[6]}`));
    const itens = tipo === "mov"
      ? [...el.processoConteudo.querySelectorAll(".linha-tempo li.movimentacao")]
          .filter((li) => datas.includes(li.dataset.data))
      : [];
    if (itens.length) itens.forEach(realcar);
    else el.painelProcesso.scrollTop = 0;
  }

  function realcar(no) {
    no.classList.remove("realce");
    void no.offsetWidth;  // reinicia a animação
    no.classList.add("realce");
    no.scrollIntoView({ block: "center", behavior: suave() });
  }

  // ---------------------------------------------------------------- selos e minuta

  function registrarTrechos(selos) {
    for (const selo of selos) {
      if (selo.tipo !== "aspas" || selo.status !== "ok" || !Array.isArray(selo.docs)) continue;
      selo.docs.forEach((id, i) => {
        if (!estado.trechosPorDoc.has(id)) estado.trechosPorDoc.set(id, new Set());
        estado.trechosPorDoc.get(id).add(selo.trechos[i]);
      });
    }
  }

  function renderizarSelos(resp) {
    const caixa = resp.el.selos;
    const detalhes = [];
    caixa.replaceChildren();
    for (const selo of resp.selos.filter((s) => s.status === "ok")) {
      if (selo.tipo === "aspas" && Array.isArray(selo.docs) && selo.docs.length) {
        const [pilula, lista] = seloAspas(selo);
        caixa.append(pilula);
        detalhes.push(lista);
      } else {
        caixa.append(criar("span", "selo-ok", `✓ ${semPonto(selo.mensagem)}`));
      }
    }
    caixa.append(...detalhes);
    for (const selo of resp.selos.filter((s) => s.status !== "ok")) caixa.append(seloAlerta(selo));
    caixa.hidden = !resp.selos.length;
  }

  // Selo de aspas conferidas: abre a lista dos trechos; cada um leva ao ponto exato do documento.
  function seloAspas(selo) {
    const pilula = botao("selo-ok", `✓ ${semPonto(selo.mensagem)}`);
    pilula.setAttribute("aria-expanded", "false");
    const lista = criar("ul", "selo-detalhe");
    lista.hidden = true;
    selo.trechos.forEach((trecho, i) => {
      const id = selo.docs[i];
      const b = botao("trecho-literal", `“${trecho}”`);
      b.dataset.doc = String(id);
      b.dataset.trecho = trecho;
      b.title = `Abrir o Doc ${id} neste trecho`;
      const li = criar("li");
      li.append(b, " ", criar("span", "muted", `— ${rotuloDoc(id)}`));
      lista.append(li);
    });
    pilula.addEventListener("click", () => {
      const abrir = lista.hidden;
      lista.hidden = !abrir;
      pilula.setAttribute("aria-expanded", String(abrir));
    });
    return [pilula, lista];
  }

  function seloAlerta(selo) {
    const caixa = criar("div", "selo-alerta");
    caixa.append(criar("span", "selo-msg", `⚠ ${selo.mensagem}`));
    if (Array.isArray(selo.trechos) && selo.trechos.length) {
      const ul = criar("ul", "selo-trechos");
      for (const t of selo.trechos) ul.append(criar("li", null, selo.tipo === "aspas" ? `“${t}”` : t));
      caixa.append(ul);
    }
    return caixa;
  }

  const textoDaFaixa = (aviso) => `${String(aviso).replace(/[.\s]+$/, "")}.`;

  function aplicarMinuta(resp, aviso) {
    if (resp.ehMinuta) return;
    resp.ehMinuta = true;
    resp.aviso = aviso;
    // A faixa é da interface: sai sempre, independentemente do que o modelo escreveu.
    const faixa = criar("div", "faixa-minuta");
    faixa.setAttribute("role", "note");
    faixa.append(criar("strong", null, `⚠ ${textoDaFaixa(aviso)}`), criar("span", null, COMPLEMENTO_FAIXA));
    resp.el.balao.hidden = false;
    resp.el.balao.prepend(faixa);
    renderizarConteudo(resp);  // agora com as lacunas de decisão destacadas
    const copiar = botao("botao-acao", ROTULO_COPIAR);
    copiar.addEventListener("click", () => copiarMinuta(resp, copiar));
    const verFontes = botao("botao-acao", "Ver fontes");
    verFontes.addEventListener("click", () => {
      mostrarAba("fontes");
      trazerPainelParaVista();
    });
    resp.el.acoes.replaceChildren(copiar, verFontes);
    resp.el.acoes.hidden = false;
  }

  async function copiarMinuta(resp, botaoCopiar) {
    const texto = `${textoDaFaixa(resp.aviso)}\n${COMPLEMENTO_FAIXA}\n\n${textoExibido(resp).trim()}\n`;
    const ok = await copiarTexto(texto);
    botaoCopiar.textContent = ok ? "Minuta copiada ✓" : "Não foi possível copiar";
    botaoCopiar.classList.toggle("copiado", ok);
    setTimeout(() => {
      botaoCopiar.textContent = ROTULO_COPIAR;
      botaoCopiar.classList.remove("copiado");
    }, 2500);
  }

  async function copiarTexto(texto) {
    try {
      await navigator.clipboard.writeText(texto);
      return true;
    } catch (_) {
      // Fora de contexto seguro (página aberta pelo IP da rede) não há navigator.clipboard.
      const area = criar("textarea", "visualmente-oculto");
      area.value = texto;
      area.setAttribute("readonly", "");
      document.body.append(area);
      area.select();
      let ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (_) {
        ok = false;
      }
      area.remove();
      return ok;
    }
  }

  // ---------------------------------------------------------------- cabeçalho e ficha

  function renderizarFoco(ficha) {
    el.focoNumero.textContent = ficha ? ficha.numero : "nenhum";
    el.focoClasse.textContent = (ficha && ficha.classe) || "";
    el.focoClasse.hidden = !(ficha && ficha.classe);
    el.focoSituacao.textContent = (ficha && ficha.situacao) || "";
    el.focoSituacao.hidden = !(ficha && ficha.situacao);
  }

  function registrarMetas(ficha) {
    for (const d of ficha.documentos || []) estado.metaDocs.set(d.id, { ...d, numero: ficha.numero });
  }

  function definirFicha(ficha) {
    estado.ficha = ficha;
    registrarMetas(ficha);
    renderizarFoco(ficha);
    renderizarFicha(ficha);
    salvarConversa();
  }

  // Ficha, contador e custo ficam guardados com a sessão: o servidor só reenvia o evento
  // "processo" quando o foco muda, então depois de recarregar a página o cabeçalho ficaria vazio.
  function salvarConversa() {
    gravarLocal(CHAVES.conversa, JSON.stringify({
      sessao: estado.sessaoId, ficha: estado.ficha, perguntas: estado.perguntas, custo: estado.custoSessao,
    }));
  }

  function restaurarConversa() {
    try {
      const salvo = JSON.parse(lerLocal(CHAVES.conversa) || "null");
      if (!salvo || salvo.sessao !== estado.sessaoId) return;
      estado.perguntas = Number(salvo.perguntas) || 0;
      estado.custoSessao = Number(salvo.custo) || 0;
      if (salvo.ficha && salvo.ficha.numero) definirFicha(salvo.ficha);
    } catch (_) {
      /* registro ilegível: começa sem foco */
    }
  }

  function renderizarFicha(ficha) {
    if (!ficha) {
      el.processoConteudo.replaceChildren(criar("p", "vazio", "Nenhum processo em foco. A ficha aparece " +
        "aqui quando o agente abre um processo: cadastro, partes, advogados, Ministério Público, " +
        "alertas e linha do tempo."));
      return;
    }
    el.processoConteudo.replaceChildren(
      criar("h2", "ficha-numero", ficha.numero),
      secaoCadastro(ficha),
      ...secaoAlertas(ficha.alertas),
      criar("h3", "subtitulo", "Partes"), listaPartes(ficha.partes),
      criar("h3", "subtitulo", "Advogados"), listaAdvogados(ficha.advogados),
      criar("h3", "subtitulo", "Ministério Público"), listaMinisterio(ficha.ministerio_publico),
      tituloLinhaDoTempo(ficha), linhaDoTempo(ficha),
    );
  }

  function secaoCadastro(f) {
    const magistrado = f.magistrado
      ? juntar(f.magistrado, f.magistrado_situacao && `situação: ${f.magistrado_situacao}`)
      : criar("span", "nao-vinculado", "não vinculado no cadastro");
    return listaChaveValor([
      ["Classe / assunto", juntar(f.classe, f.assunto)],
      ["Comarca / vara", juntar(f.comarca, f.vara)],
      ["Magistrado", magistrado],
      ["Situação", f.situacao || "—"],
      ["Autuação", N.formatarData(f.data_autuacao)],
      ["Sentença", N.formatarData(f.data_sentenca)],
      ["Valor da causa", N.formatarBRL(f.valor_causa)],
    ]);
  }

  function secaoAlertas(alertas) {
    const titulo = criar("h3", "subtitulo", "Alertas de qualidade dos dados");
    if (!Array.isArray(alertas) || !alertas.length) {
      return [titulo, criar("p", "vazio", "Nenhum alerta para este processo.")];
    }
    return [titulo, ...alertas.map((alerta) => {
      const p = criar("p", "alerta-processo");
      p.append(fragmentoDecorado(String(alerta), false));  // "[Doc 946 …]" vira chip
      return p;
    })];
  }

  function listaPartes(partes) {
    if (!Array.isArray(partes) || !partes.length) return criar("p", "vazio", "Nenhuma parte no cadastro.");
    const ul = criar("ul", "lista-ficha");
    for (const p of partes) {
      const li = criar("li");
      li.append(criar("span", "polo", p.polo || "—"), p.nome || "—");
      if (p.cpf_cnpj) {
        const tipo = /\//.test(p.cpf_cnpj) ? "CNPJ" : "CPF";
        li.append(criar("span", "detalhe", `${tipo} ${p.cpf_cnpj}`));  // já vem mascarado da API
      }
      ul.append(li);
    }
    return ul;
  }

  function listaAdvogados(advogados) {
    if (!Array.isArray(advogados) || !advogados.length) {
      return criar("p", "vazio", "Nenhum advogado identificado nos documentos.");
    }
    const ul = criar("ul", "lista-ficha");
    for (const a of advogados) {
      const li = criar("li");
      li.append(criar("strong", null, a.nome || "—"), ` — ${a.oab || "OAB não informada"}`);
      const detalhe = criar("span", "detalhe");
      const base = Array.isArray(a.base_inferencia) ? a.base_inferencia : [];
      if (base.length) {
        detalhe.append(`${POLOS[a.polo_inferido] || a.polo_inferido}, inferido pelo tipo das peças: `);
        base.forEach((ref, i) => {
          if (i) detalhe.append(" ");
          detalhe.append(chipReferencia(ref));
        });
      } else {
        detalhe.append("polo não inferido: não assina petição inicial, réplica nem contestação");
      }
      li.append(detalhe);
      ul.append(li);
    }
    return ul;
  }

  function listaMinisterio(manifestacoes) {
    if (!Array.isArray(manifestacoes) || !manifestacoes.length) {
      return criar("p", "vazio", "Sem manifestação do Ministério Público nos documentos.");
    }
    const ul = criar("ul", "lista-ficha");
    for (const m of manifestacoes) {
      const li = criar("li");
      li.append(m.autor || "Ministério Público", " · ", chipReferencia(m.documento));
      ul.append(li);
    }
    return ul;
  }

  function tituloLinhaDoTempo(f) {
    const movs = (f.movimentacoes || []).length;
    const docs = (f.documentos || []).length;
    const titulo = criar("h3", "subtitulo", "Linha do tempo");
    const contagem = criar("p", "vazio", `${plural(movs, "movimentação", "movimentações")} e ` +
                                        `${plural(docs, "documento", "documentos")}, por data`);
    const frag = document.createDocumentFragment();
    frag.append(titulo, contagem);
    return frag;
  }

  function linhaDoTempo(f) {
    const itens = [
      ...(f.movimentacoes || []).map((m, i) => ({ data: m.data, ordem: 0, i, mov: m })),
      ...(f.documentos || []).map((d, i) => ({ data: d.data_juntada, ordem: 1, i, doc: d })),
    ].sort((a, b) => String(a.data || "9999").localeCompare(String(b.data || "9999")) ||
                     a.ordem - b.ordem || a.i - b.i);
    if (!itens.length) return criar("p", "vazio", "Sem movimentações nem documentos.");
    const ol = criar("ol", "linha-tempo");
    for (const item of itens) {
      const li = criar("li", item.doc ? "documento" : "movimentacao");
      const quando = criar("time", null, N.formatarData(item.data));
      if (item.data) {
        li.dataset.data = item.data;
        quando.dateTime = item.data;
      }
      li.append(quando, " ");
      if (item.doc) li.append(botaoDoc(item.doc.id, `Doc ${item.doc.id} – ${item.doc.tipo}`));
      else li.append(item.mov.descricao || "—");
      ol.append(li);
    }
    return ol;
  }

  // ---------------------------------------------------------------- aba Fontes

  function renderizarFontesVazio() {
    el.fontesDocumento.replaceChildren(criar("p", "vazio", "Clique numa citação de documento na " +
      "conversa (por exemplo, Doc 93) para abrir aqui o texto integral, com os trechos citados " +
      "destacados. Só abrem documentos de processos consultados nesta conversa."));
  }

  function atualizarListaFontes(ids) {
    estado.fontesCitadas = [...ids, ...estado.fontesCitadas.filter((id) => !ids.includes(id))];
    renderizarListaFontes();
  }

  function renderizarListaFontes() {
    el.fontesItens.replaceChildren(...estado.fontesCitadas.map((id) => {
      const b = botao("item-fonte", rotuloDoc(id, { comData: true }));
      b.dataset.doc = String(id);
      if (id === estado.docAberto) b.setAttribute("aria-current", "true");
      const li = criar("li");
      li.append(b);
      return li;
    }));
    el.fontesLista.hidden = !estado.fontesCitadas.length;
  }

  async function abrirDocumento(id, trecho) {
    mostrarAba("fontes");
    trazerPainelParaVista();
    const pedido = ++estado.pedidoDoc;  // só o último clique desenha
    estado.docAberto = id;
    renderizarListaFontes();
    el.fontesDocumento.replaceChildren(criar("p", "vazio", `Abrindo ${rotuloDoc(id)}…`));
    try {
      const doc = await obterDocumento(id);
      if (pedido === estado.pedidoDoc) renderizarDocumento(doc, { trecho, rolar: true });
    } catch (erro) {
      if (pedido !== estado.pedidoDoc) return;
      const fora = erro.status === 403;
      el.fontesDocumento.replaceChildren(
        criar("p", "erro-doc", fora ? "Documento fora do escopo desta conversa."
                                    : "Não foi possível abrir o documento agora."),
        criar("p", "vazio", fora ? "Só abrem aqui os documentos de processos consultados nesta conversa."
                                 : "Confira se o servidor está no ar e tente de novo."));
    }
  }

  function renderizarDocumento(doc, { trecho, rolar }) {
    const texto = doc.texto || "";
    const trechos = [...(estado.trechosPorDoc.get(doc.id) || [])];
    const intervalos = N.trechosParaDestacar(texto, trechos);
    const achados = trechos.filter((t) => N.trechosParaDestacar(texto, [t]).length).length;
    const cabecalho = criar("header", "doc-cabecalho");
    cabecalho.append(criar("h2", null, `Doc ${doc.id} – ${doc.tipo || "documento"}`));
    cabecalho.append(criar("p", "doc-meta", juntar(
      N.formatarData(doc.data_juntada), doc.autor,
      doc.paginas && plural(doc.paginas, "página", "páginas"), doc.numero && `processo ${doc.numero}`)));
    if (achados) {
      cabecalho.append(criar("p", "doc-nota",
        plural(achados, "trecho citado destacado", "trechos citados destacados")));
    }
    const corpo = criar("div", "doc-texto");
    let pos = 0;
    for (const { inicio, fim } of intervalos) {
      corpo.append(texto.slice(pos, inicio));
      const marca = criar("mark", "destaque", texto.slice(inicio, fim));
      marca.dataset.inicio = String(inicio);
      marca.dataset.fim = String(fim);
      corpo.append(marca);
      pos = fim;
    }
    corpo.append(texto ? texto.slice(pos) : "(documento sem texto no banco)");
    el.fontesDocumento.replaceChildren(cabecalho, corpo);
    if (rolar) rolarAteDestaque(corpo, texto, trecho);
  }

  function rolarAteDestaque(corpo, texto, trecho) {
    const marcas = [...corpo.querySelectorAll("mark.destaque")];
    let alvo = marcas[0];
    if (trecho) {
      const [foco] = N.trechosParaDestacar(texto, [trecho]);
      const certa = foco && marcas.find((m) => Number(m.dataset.inicio) <= foco.inicio &&
                                             foco.inicio < Number(m.dataset.fim));
      if (certa) {
        alvo = certa;
        certa.classList.add("em-foco");
      }
    }
    if (alvo) alvo.scrollIntoView({ block: "center", behavior: suave() });
    else el.painelFontes.scrollTop = 0;
  }

  // Trechos conferidos chegam no fim da resposta: o documento já aberto ganha os destaques.
  function redesenharDocumentoAberto() {
    const id = estado.docAberto;
    if (id !== null && estado.docs.has(id) && estado.trechosPorDoc.has(id)) {
      renderizarDocumento(estado.docs.get(id), { rolar: false });
    }
  }

  // ---------------------------------------------------------------- aba Como cheguei aqui

  function renderizarComoVazio() {
    el.comoConteudo.replaceChildren(criar("p", "vazio", "Aqui aparece como a última resposta foi " +
      "construída: ferramentas chamadas e argumentos, o SQL exato, a duração de cada passo, os " +
      "tokens, o custo, a latência, o modelo, o provedor e o resultado da verificação."));
  }

  function iniciarPainelComo(resp) {
    const lista = criar("ol", "passos-painel");
    const pergunta = criar("div");
    pergunta.append("Pergunta recebida · processo em foco: ",
                    criar("strong", null, estado.ficha ? estado.ficha.numero : "nenhum"),
                    criar("p", "pergunta-citada", resp.pergunta));
    const primeiro = criar("li");
    primeiro.append(pergunta);
    // Resposta e verificação têm lugar fixo no fim: os passos de ferramenta entram antes deles.
    const slotResposta = criar("li");
    const slotVerificacao = criar("li");
    slotResposta.hidden = true;
    slotVerificacao.hidden = true;
    lista.append(primeiro, slotResposta, slotVerificacao);
    const pendente = criar("p", "vazio", "Resposta em andamento…");
    el.comoConteudo.replaceChildren(criar("h2", "subtitulo", "Última resposta"), lista, pendente);
    resp.painel = { lista, slotResposta, slotVerificacao, pendente };
  }

  function adicionarPassoFerramenta(resp, ev) {
    const corpo = criar("div");
    corpo.append("⚙ ", criar("strong", null, ev.nome), ` → ${ev.resumo || "—"} · `,
                 criar("span", "muted", N.formatarDuracao(ev.duracao_ms)));
    const args = ev.args || {};
    if (typeof args.sql === "string") corpo.append(criar("pre", "sql", args.sql));
    const outros = Object.entries(args).filter(([chave]) => chave !== "sql");
    if (outros.length) corpo.append(listaChaveValor(outros.map(([k, v]) => [k, String(v)])));
    const li = criar("li");
    li.append(corpo);
    resp.painel.lista.insertBefore(li, resp.painel.slotResposta);
  }

  function preencherRespostaPainel(resp) {
    const { slotResposta, pendente } = resp.painel;
    const corpo = criar("div");
    if (!resp.uso || !Object.keys(resp.uso).length) {  // "fim" sem uso: o modelo falhou antes
      corpo.append("✍ Resposta não concluída: sem registro de tokens nem custo.");
    } else {
      const u = resp.uso;
      corpo.append("✍ ", criar("strong", null, "Resposta"));
      corpo.append(listaChaveValor([
        ["Tokens de entrada", N.formatarNumero(u.prompt)],
        ["Tokens de saída", N.formatarNumero(u.completion)],
        ["dos quais raciocínio", N.formatarNumero(u.raciocinio)],
        ["Custo", N.formatarCusto(u.cost)],
        ["Latência", N.formatarDuracao(u.latencia_ms)],
        ["Modelo", u.modelo || "—"],
        ["Provedor", u.provedor || "—"],
      ]));
    }
    slotResposta.replaceChildren(corpo);
    slotResposta.hidden = false;
    pendente.remove();
  }

  function preencherVerificacaoPainel(resp) {
    const alertas = resp.selos.filter((s) => s.status !== "ok").length;
    const corpo = criar("div");
    corpo.append(alertas ? "⚠ " : "✓ ", criar("strong", null, "Verificação"),
                 ` · ${plural(resp.selos.length - alertas, "conferência ok", "conferências ok")}, ` +
                 plural(alertas, "alerta", "alertas"));
    const ul = criar("ul", "lista-selos");
    for (const selo of resp.selos) {
      const ok = selo.status === "ok";
      const li = criar("li", ok ? "ok" : "alerta", `${ok ? "✓" : "⚠"} ${selo.mensagem}`);
      if (!ok && Array.isArray(selo.trechos) && selo.trechos.length) {
        li.append(criar("span", "trechos", selo.trechos.join(" · ")));
      }
      ul.append(li);
    }
    corpo.append(ul);
    resp.painel.slotVerificacao.replaceChildren(corpo);
    resp.painel.slotVerificacao.hidden = false;
  }

  function renderizarCusto() {
    const caixa = el.comoCusto;
    caixa.replaceChildren();
    if (estado.perguntas) {
      caixa.append(criar("p", null, `Esta conversa: ${plural(estado.perguntas, "pergunta", "perguntas")}` +
                                    ` · ${N.formatarCusto(estado.custoSessao)}`));
    }
    const s = estado.saude;
    if (!s) {
      caixa.append(criar("p", null, "Custo acumulado indisponível: a API não respondeu."));
      return;
    }
    caixa.append(criar("p", null, `Custo acumulado do protótipo: ${N.formatarCusto(s.custo_acumulado)}` +
                                  ` de ${N.formatarCusto(s.orcamento, 2)} (teto)`));
    const fracao = s.orcamento > 0 ? Math.min(1, s.custo_acumulado / s.orcamento) : 0;
    const barra = criar("div", "barra");
    barra.setAttribute("role", "img");
    barra.setAttribute("aria-label", `${Math.round(fracao * 100)}% do teto usado`);
    barra.classList.toggle("perto", fracao >= 0.8);
    const cheio = criar("span");
    cheio.style.width = `${(fracao * 100).toFixed(1)}%`;
    barra.append(cheio);
    caixa.append(barra);
  }

  // ---------------------------------------------------------------- conversa

  function limparTela() {
    Object.assign(estado, { ficha: null, docAberto: null, perguntas: 0, custoSessao: 0, fontesCitadas: [] });
    estado.metaDocs.clear();
    estado.docs.clear();
    estado.trechosPorDoc.clear();
    estado.pedidoDoc += 1;
    el.boasVindas.hidden = false;
    el.mensagens.replaceChildren(el.boasVindas);
    modoEnvio(false);
    renderizarFoco(null);
    renderizarFontesVazio();
    renderizarListaFontes();
    renderizarComoVazio();
    renderizarCusto();
    renderizarFicha(null);
    $("aba-processo").classList.remove("novidade");
  }

  async function novaConversa() {
    estado.conversa += 1;
    if (estado.emAndamento) estado.emAndamento.controle.abort();
    estado.emAndamento = null;
    limparTela();
    gravarLocal(CHAVES.conversa, null);
    try {
      await novaSessao();
    } catch (_) {
      estado.sessaoId = null;
      gravarLocal(CHAVES.sessao, null);
      avisoSistema("Não foi possível abrir uma nova conversa: o servidor não respondeu.");
    }
    atualizarSaude();
    el.pergunta.focus();
  }

  function usarSugestao(sugestao) {
    el.pergunta.value = sugestao.dataset.pergunta;
    ajustarAltura();
    el.pergunta.focus();
    el.pergunta.setSelectionRange(el.pergunta.value.length, el.pergunta.value.length);
  }

  function ligarEventos() {
    el.formulario.addEventListener("submit", (evento) => {
      evento.preventDefault();
      if (estado.emAndamento) estado.emAndamento.controle.abort();  // o botão vira "Parar"
      else enviar(el.pergunta.value);
    });
    el.pergunta.addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" && !evento.shiftKey && !evento.isComposing) {
        evento.preventDefault();
        if (!estado.emAndamento) enviar(el.pergunta.value);
      }
    });
    el.pergunta.addEventListener("input", ajustarAltura);
    for (const sugestao of document.querySelectorAll(".sugestao")) {
      sugestao.addEventListener("click", () => usarSugestao(sugestao));
    }
    el.nova.addEventListener("click", novaConversa);
    el.tema.addEventListener("click", alternarTema);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", atualizarBotaoTema);
    for (const aba of document.querySelectorAll('[role="tab"]')) {
      aba.addEventListener("click", () => mostrarAba(aba.dataset.aba));
      aba.addEventListener("keydown", teclaNasAbas);
    }
    document.addEventListener("click", aoClicarFonte);
  }

  async function iniciar() {
    atualizarBotaoTema();
    ligarEventos();
    limparTela();
    const guardada = lerLocal(CHAVES.sessao);
    estado.sessaoId = guardada && RX_ID_SESSAO.test(guardada) ? guardada : null;
    if (estado.sessaoId) {
      restaurarConversa();
    } else {
      try {
        await novaSessao();
      } catch (_) {
        avisoSistema("O servidor não respondeu; a conversa começa quando ele voltar.");
      }
    }
    atualizarSaude();
    el.pergunta.focus();
  }

  iniciar();
})();
