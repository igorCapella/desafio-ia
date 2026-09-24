# Decisões

Este documento registra as decisões do protótipo. Para cada uma, traz o contexto, a escolha, as alternativas
descartadas e a evidência. Depois responde às cinco perguntas da arguição e lista o que as revisões de segurança
encontraram.

**Fontes dos números.** Salvo indicação, os números vêm de seis fontes:

- o spike de modelos ([RESULTADOS.md](docs/pesquisa/2026-09-23-spike-modelos/RESULTADOS.md));
- as três rodadas reais de avaliação ([evals/resultados/](evals/resultados/));
- o log de auditoria real (`scripts/resumo_logs.py`);
- a reverificação das respostas gravadas com o verificador de hoje (`evals/reverificar.py`);
- a suíte de testes;
- o diário de execução, mantido fora deste repositório durante a implementação. Cada decisão tomada no caminho foi
  registrada ali, com o achado que a motivou; este documento cita cada uma como "Ruling N" e resume aqui o conteúdo
  relevante (como o [CLAUDE.md](CLAUDE.md) já diz).

Onde um número não foi medido, o texto diz.

- [Parte 1: decisões](#parte-1-decisões)
- [Parte 2: as cinco perguntas da arguição](#parte-2-as-cinco-perguntas-da-arguição)
- [Parte 3: segurança, o que as revisões encontraram](#parte-3-segurança-o-que-as-revisões-encontraram)

## Parte 1: decisões

### 1. Modelo: DeepSeek V4.1 Flash, com o V4 Pro 0813 de reserva

**Contexto.** O agente precisa chamar ferramentas em sequência e responder em português. Ele não pode inventar nem
decidir o mérito numa minuta. A chave do OpenRouter do desafio tem limite de US$ 4.

**Escolha.** `deepseek/deepseek-v4.1-flash` via OpenRouter, com `deepseek/deepseek-v4-pro-0813` como reserva na lista
de modelos de cada requisição.

**Evidência.** O spike de 23/09/2026 rodou o mesmo agente mínimo com cada modelo. Foram 9 turnos em 6 conversas,
cobrindo os 5 requisitos e a minuta, com gabaritos calculados no banco. Houve checagens automáticas e revisão manual
de todas as respostas.

| Modelo | Tarefas corretas | Contradições do processo da demo (de 3) | Minuta | Súmulas de fora dos autos | Custo da bateria | Latência média por turno |
|---|---|---|---|---|---|---|
| DeepSeek V4 Flash | 9/9 | suavizou ("os dados estão consistentes") | decidiu o mérito | 2, uma com texto inventado (Súmula 403) | US$ 0,006 | 16 s |
| **DeepSeek V4.1 Flash** | **9/9** | **apontou as 3** | **dispositivo entre colchetes** | **0** | US$ 0,017 | 34 s |
| DeepSeek V4 Pro 0813 | 9/9 | apontou as 3 | dispositivo entre colchetes | 0 | US$ 0,035 | 41 s (minuta: 200 s) |
| Gemini 3.5 Flash (chave grátis) | 6/7 executadas (+2 sem cota) | apontou as 3 | decidiu o mérito | 2 (corretas) | US$ 0 | 33 s |

**Alternativas descartadas.**

- **V4 Flash.** Inventou o texto da Súmula 403 do STJ. A súmula real trata de publicação não autorizada de imagem.
  Ele também leu uma contradição dos autos como "os dados estão consistentes".
- **Gemini 3.5 Flash.** Decidiu o mérito na minuta. Também transformou uma inferência em fato: disse que a magistrada
  da unidade "é a responsável" por um processo sem magistrado vinculado. A chave gratuita permite 20 requisições por
  dia por modelo, e o plano gratuito deixa o Google usar os dados enviados.
- **V4 Pro 0813.** Empatou em qualidade com o V4.1 Flash e foi de 2 a 6 vezes mais lento. Continua como reserva.

Nas aspas, o V4.1 Flash errou 2 de cerca de 39 trechos, com paráfrases leves ("pleiteia" onde o texto diz
"pleiteando"). Isso levou ao verificador de aspas (decisão 8). No produto, as três rodadas de avaliação com o V4.1
Flash foram de 23 para 25 casos aprovados, de 25, nas checagens objetivas (pergunta 2). Os pesos do DeepSeek V4 são
abertos (licença MIT): com dados sigilosos, o mesmo modelo pode rodar on-premises (pergunta 5).

### 2. Nível de raciocínio: `high`

**Contexto.** O DeepSeek V4.1 Flash aceita três níveis de raciocínio: `low`, `high` (o padrão) e `max`. Mais
raciocínio custa tempo, e a minuta já é a resposta mais longa.

**Escolha.** `high` em tudo.

**Evidência.** O spike comparou `high` e `max` nas conversas mais difíceis (resumo com contradições, minuta e processo
sem magistrado). O provedor ficou fixo, com 2 repetições de cada configuração, a um custo de US$ 0,046.

| Configuração | Contradições (de 3) | Minuta decide o mérito? | Aspas literais | Raciocínio (tokens) | Latência da minuta | Custo |
|---|---|---|---|---|---|---|
| high, repetição 1 | 3 | não | 27/28 | 3.482 | 75 s | US$ 0,0077 |
| high, repetição 2 | 3 | não | 17/18 | 2.300 | 63 s | US$ 0,0067 |
| max, repetição 1 | 3 | não | 14/14 | 19.327 | 190 s | US$ 0,0132 |
| max, repetição 2 | 3 | não | 21/21 | 30.773 | 318 s | US$ 0,0185 |

O `max` gerou de 6 a 10 vezes mais raciocínio sem mudar nenhum critério crítico. O ganho ficou só nas aspas: 100%
literais, contra cerca de 96% no `high`. Em troca, a minuta ficou de 3 a 4 vezes mais lenta. A fidelidade das aspas
ficou com um verificador determinístico, mais barato e mais confiável que raciocínio extra. Sem raciocínio, o modelo
errou uma conta simples (respondeu 16 em vez de 24), então o raciocínio fica ligado.

### 3. Arquitetura do agente: ferramentas de domínio, SQL protegido e verificação

**Contexto.** O desafio pede que o agente consulte o banco sozinho e fundamente as respostas. O banco tem armadilhas
que dão respostas erradas em silêncio (decisão 7).

**Escolha.** O modelo escolhe entre três ferramentas, num laço explícito:

- `obter_dossie` traz um processo inteiro numa chamada: cadastro, partes, advogados com o polo inferido, Ministério
  Público, movimentações, a íntegra dos documentos e os alertas de qualidade calculados pelo código.
- `buscar_processos` localiza processos quando falta o número.
- `consultar_sql` faz contagens e agregações, com um único SELECT por vez e só sobre as visões.

Depois de cada resposta, uma camada de verificação por código confere a forma da resposta (decisão 8).

**Alternativas descartadas.**

- **Só gerar SQL.** As armadilhas de grafia dão número errado sem aviso. Contando os julgados em Joinville: a visão
  (comarca da unidade e situação normalizada) dá 190; só a comarca crua, 180; só a situação crua, 178; as duas cruas,
  168.
- **RAG.** O dossiê de um processo deste banco cabe inteiro no contexto. O maior documento tem 2.589 caracteres, e o
  resumo do processo da demo usou cerca de 10 mil tokens de entrada.
- **Fluxo fixo.** Não seria autônomo.
- **Framework de agentes.** Esconderia o laço que a arguição quer ver. O laço tem 215 linhas (`app/agente/ciclo.py`).

**Evidência.** Os dois casos de agregação com armadilha de comarca passaram nas três rodadas: julgados em Joinville
(190) e total de Joinville (899). Na 3ª rodada, passaram também os casos de resumo, partes, decisão, limites e
minutas. As falhas das rodadas anteriores estão explicadas na pergunta 2.

### 4. Linguagem: Python, não Go

**Contexto.** A pergunta natural é se uma linguagem compilada deixaria o agente mais rápido.

**Escolha.** Python ≥ 3.12, com FastAPI, sqlite3 da biblioteca padrão e pytest.

**Evidência.** O tempo que o usuário espera é do modelo, três ordens de grandeza acima do código:

| Medição | Código | Modelo |
|---|---|---|
| Spike (spec, seção 2) | 0,3 a 2 ms por consulta | 18,5 s (mediana) |
| Log real do app | `obter_dossie` de 3 a 18 ms; `buscar_processos` 11 ms; `consultar_sql` 9 ms | turno de 4,2 a 32,7 s (p50 de 8,2 s) |
| Avaliações (28 turnos por rodada) | — | mediana de 11,7 a 14,1 s por turno |
| Alertas dos 10.000 processos, calculados de uma vez | 0,58 s no total; pior chamada, 10 ms | — |

No log, a primeira consulta SQL levou 164 ms: a cópia em memória do banco ainda era montada na hora. Hoje ela é
montada na subida do app, em 0,18 s. Go não mudaria a espera do usuário. Python traz o ecossistema e a velocidade de
iteração.

**Limitação conhecida.** Uma consulta pesada que usa a função Python `normalizar` no SQL segura o GIL e atrasa as
outras requisições. Com muitos usuários, o SQL iria para um banco separado (pergunta 5).

### 5. Interface e streaming (SSE)

**Contexto.** A banca vai ver a interface num projetor, e a minuta leva dezenas de segundos para ficar pronta.

**Escolha.** FastAPI com SSE nativo (`fastapi.sse`) e interface própria em HTML, CSS e JavaScript, sem etapa de
build. As bibliotecas marked e DOMPurify ficam no repositório, sem CDN, e a CSP proíbe script inline. O layout foi
aprovado em mockup: chat à esquerda e painel com as abas Fontes, Como cheguei aqui e Processo.

**Alternativas descartadas.**

- **Chainlit.** Visual genérico e pouco controle sobre os chips de citação e a faixa da minuta.
- **Next.js.** Um segundo ecossistema, com build, para um protótipo.

**Evidência.** O streaming é necessário: a minuta levou de 29,9 a 33,3 s nas três rodadas, servida pelo
AtlasCloud. No spike, com o provedor fixado no DeepInfra, levou de 63 a 75 s. A revisão da interface foi feita ao
vivo no navegador. Ela conferiu os 12 requisitos, sem nenhuma mensagem no console durante a sessão inteira, e
contraste AA. Um achado da validação: o SSE nativo do FastAPI 0.141 exige que o endpoint seja o próprio gerador de
eventos. O uso previsto no plano quebrava e codificaria o JSON duas vezes (Ruling 19).

### 6. Cliente LLM próprio (httpx)

**Contexto.** O produto depende de campos específicos do OpenRouter e precisa trocar de provedor sem mudar código.

**Escolha.** Um cliente HTTP próprio (`app/agente/llm.py`, 151 linhas) no protocolo compatível com a OpenAI. A
`LLM_BASE_URL` é configurável.

**Alternativas descartadas.** O SDK `openai`: a v3.19 era recente, e a documentação consultável ia só até a v2.11. Os
SDKs de cada provedor também ficaram de fora.

**Evidência.** O cliente próprio dá controle dos campos que o produto usa: `usage.cost`, `provider` e
`reasoning_details`. O teste ao vivo da revisão mostrou dois comportamentos que um SDK esconderia:

- O OpenRouter repete o `finish_reason` no último pedaço do streaming. O parser emitia os eventos duas vezes; foi
  corrigido com teste (Ruling 12).
- O provedor muda entre chamadas: no mesmo teste vieram Makora e StreamLake.

O `reasoning_details` remontado dos pedaços do streaming foi aceito de volta pelo provedor (9 fragmentos, 1 bloco).
Trocar para um vLLM on-premises é trocar a URL.

### 7. Visões normalizadas como única fonte

**Contexto.** O banco do desafio tem inconsistências que dão respostas erradas sem aviso. O banco original não pode
ser alterado.

**Escolha.** Seis visões (`v_processo`, `v_partes`, `v_documentos`, `v_movimentacoes`, `v_magistrados` e
`v_unidades`), criadas como `TEMP VIEW` em cada conexão. As ferramentas e o SQL do modelo só enxergam essas visões.

| Armadilha no banco | Tratamento na visão |
|---|---|
| `situacao` com 12 grafias | normalizada em 4 valores (Julgado, Arquivado, Em andamento, Suspenso); a grafia original fica em `situacao_original` |
| `processo.comarca` com 230 grafias para 60 comarcas (normalizar acento e caixa só chega a 64) | a comarca vem de `unidade.comarca` |
| `parte.tipo` diverge do polo em 1.633 vínculos | o papel da parte vem de `processo_parte.polo` |
| 402 movimentações órfãs | excluídas pela junção com `processo` |
| advogado e OAB dentro do texto de `documento.autor` | extraídos para as colunas `advogado` e `oab` |
| CPF completo em `parte.documento` | mascarado no padrão `***.550.862-**`; o CNPJ fica completo, porque não é dado pessoal |

**Alternativas descartadas.** Uma foi deixar o modelo lidar com as grafias no SQL: ele pode acertar às vezes, mas o
erro é silencioso. A outra foi corrigir o banco, o que é proibido.

**Evidência.** A revisão da camada de dados conferiu três coisas: as visões têm as mesmas contagens da base (menos as
402 órfãs), `v_partes` não tem nenhum CPF completo e as 4 situações somam 10.000. A extração de advogado e OAB
acertou 419 de 419 casos no banco real. A máscara processou 11.795 CPFs e 2.838 CNPJs sem falha. Os alertas de
qualidade, calculados pelo código sobre as visões, reproduziram todas as contagens da spec nos 10.000 processos.
Alguns exemplos:
6.309 processos sem documentos (63%), 1.044 sem magistrado vinculado, 309 com assinatura divergente e 765 com data de
audiência divergente.

### 8. Verificação que marca e não corrige

**Contexto.** O leitor trata aspas como texto literal e uma citação como prova. No spike, 5 de cerca de 65 trechos
entre aspas não estavam nas fontes, e o V4 Flash inventou o texto de uma súmula.

**Escolha.** Depois de cada resposta, um código determinístico confere a forma da resposta contra o que foi de fato
lido na conversa. O resultado vira selos, "ok" ou "alerta", que a interface mostra abaixo da resposta e o log guarda.
O texto do modelo não é alterado.

| Selo | O que confere |
|---|---|
| citação | `[Doc n]` lido nesta conversa, inclusive dentro de um marcador combinado (`[Cadastro; Doc n]`) ou num intervalo (`[Docs n a m]`, que confere as duas pontas); `[Mov data – descrição]` entre as movimentações lidas (um período vale se as duas pontas foram lidas); `[SQL]` só se houve consulta no turno |
| aspas | trecho entre aspas com 20 caracteres ou mais é literal nos documentos ou no texto devolvido pelas ferramentas; confere por fragmentos quando há reticências, exige palavras inteiras nas pontas e trata aspas simples, duplas e curvas como o mesmo caractere |
| norma | "Súmula N" e "art. N" (com ou sem ponto de milhar, como em "art. 1.699") aparecem nos autos lidos (documentos e o que as ferramentas mostraram: movimentações, cadastro, buscas e SQL) ou vêm marcados com `[verificar]`, com ou sem explicação |
| minuta | decisão de mérito fora dos colchetes — "julgo (parcial/total/integralmente) procedente(s)/improcedente(s)/extinto", "condeno", "decreto", "acolho", "rejeito" ou "homologo" —, nome do magistrado na assinatura, minuta de processo sem documentos, processo já julgado sem aviso; a resposta que redige a minuta depois de confirmar um pedido anterior ("pode redigir") também conta como minuta |
| processo | todo número de processo citado na resposta é o processo em foco ou um processo consultado |
| dados pessoais | nenhum CPF completo na resposta, exceto o que o próprio usuário digitou |

Quando a resposta é uma minuta, a interface sempre mostra a faixa "PROPOSTA DE TEXTO GERADA POR IA — NÃO É SENTENÇA
PROFERIDA", independentemente do que o modelo escreveu.

**Alternativa descartada.** Reescrever automaticamente a resposta reprovada. A reescrita esconde o erro de quem lê,
acrescenta cerca de 60 s e pode criar um erro novo.

**Evidência.** Nas três rodadas de avaliação, os selos deram 20, 18 e 7 alertas na época. Com o verificador de hoje,
as mesmas respostas dão 2, 7 e 4. Qualquer pessoa pode reproduzir esses números, sem chamar o modelo:

```bash
uv run python -m evals.reverificar evals/resultados/2026-09-24_1527.json   # 20 alertas na época -> 2
uv run python -m evals.reverificar evals/resultados/2026-09-24_1559.json   # 18 -> 7
uv run python -m evals.reverificar evals/resultados/2026-09-24_1647.json   # 7 -> 4
```

O script refaz as consultas gravadas em cada turno, que são determinísticas sobre o banco, remonta a sessão e roda o
verificador de hoje sobre a resposta gravada. Os relatórios `evals/resultados/*.md` mostram os selos como eram na
época.

A queda veio de falsos positivos do próprio verificador. Todos foram achados lendo as respostas reais e corrigidos
com teste, em três etapas:

1. **Integrações 2 e 3.** As correções foram:
   - menção ao magistrado lida como assinatura;
   - reticências numa citação da sentença;
   - pareamento de aspas;
   - eco da pergunta;
   - texto da própria ferramenta entre aspas;
   - marcadores com vários documentos.

   O período de movimentações num só marcador passou a ser aceito, e o prompt passou a documentar essa forma. Com
   essas correções, os totais ficaram em 5, 10 e 7.
2. **Releitura das respostas para escrever esta documentação (Ruling 34).** Os alertas de norma, que tinham sido
   classificados como "norma citada de memória", eram falsos:
   - "art. 40" (casos C04, C09 e C20) está na descrição de uma movimentação lida, "Arquivamento Provisório (art. 40
     LEF)". Essa descrição aparece em 1.676 movimentações do banco, e o verificador só procurava nos documentos.
   - "art. 485" (C01, 3ª rodada) veio marcado como "[verificar — dispositivo não citado nos autos]", e só a marca
     exata "[verificar]" valia.

   Com a correção, os totais caíram para 3, 7 e 4.
3. **Reclassificação dos alertas restantes (Ruling 35).** Na 1ª rodada, o C05 citou literalmente um alerta da
   ferramenta que tem aspas internas. O texto das ferramentas era guardado em JSON, com as aspas internas escapadas,
   e o modelo trocou as aspas internas por simples. Com a correção, os totais ficaram em 2, 7 e 4.

Os 13 alertas que restam foram conferidos um a um contra as fontes, e todos são verdadeiros:

| Classe | Onde |
|---|---|
| `[Mov ...]` sem data | 1ª rodada, C02 |
| `[SQL]` marcado sem consulta: o modelo pôs `[SQL]` num resultado de `obter_dossie` | 1ª rodada, C11; 2ª rodada, C11 e C16 |
| aspas não literais: "CPC" no lugar de "Código de Processo Civil" | 2ª rodada, C02 |
| aspas não literais: "(quinze)" omitido de "no prazo de 15 (quinze) dias" | 2ª rodada, C14 |
| aspas não literais: "do" omitido de "do fato, do dano e do nexo de causalidade" | 2ª rodada, C23; 3ª rodada, C23 e C24 |
| aspas não literais: o campo da ferramenta citado como "polo_inferido: ativo" | 3ª rodada, C21 |
| aspas de ênfase ou autocitação: "escolher não mostrar", "ordem cronológica possível" e "magistrada da unidade, sem vínculo confirmado com o processo" | 2ª rodada, C16 e C21; 3ª rodada, C05 |

O prompt não foi ajustado para os alertas verdadeiros sumirem. A regra de aspas literais já existia, e o selo é a
defesa.

**Limite declarado.** A verificação confere a forma, não o sentido: a fonte existe, o trecho é literal, a norma está
nos autos. O sentido fica com as avaliações e com a revisão humana. Um exemplo aparece na segunda rodada: o juiz
pegou uma afirmação sem base, que nenhum selo pegaria (pergunta 2).

### 9. Privacidade

**Escolha e evidência.**

- **Roteamento.** As requisições pedem `data_collection: deny`, reforçado por um filtro da conta contra provedores que
  treinam com os dados. O filtro tirou o provedor oficial da DeepSeek e deixou 25 de 26 endpoints. O pedido exige
  quantização fp8 ou mais precisa, o que deixa de fora os endpoints em fp4. Nas três rodadas, as chamadas passaram
  por 6 provedores terceiros: AtlasCloud, CoreWeave, DeepInfra, GMICloud, Novita e StreamLake.
- **CPF.**
  - As visões mostram o CPF mascarado, e a máscara é fail-closed: um valor fora do padrão tem todos os dígitos
    trocados.
  - O SQL do modelo só alcança a cópia mascarada.
  - A busca por CPF só aceita um número que o próprio usuário digitou. A resposta pode repetir esse número para
    confirmar a busca: é o único CPF completo que ela pode conter (nas avaliações, o CPF sintético 999.550.862-21
    do caso C25 aparece assim nos relatórios). O log mascara inclusive esse.
  - O selo de dados pessoais confere a resposta.
  - O log mascara CPF em todo campo de texto e remove chaves.
- **Documentos.** O painel só serve documentos lidos na conversa.
- **Segredos.** A chave fica só no `.env`, que o git ignora.
- **Pendência.** Trocar as chaves de API depois do desafio, porque elas foram compartilhadas no chat de
  desenvolvimento.

## Parte 2: as cinco perguntas da arguição

### 1. Arquitetura e alternativas descartadas

A arquitetura está no diagrama do [README](README.md#arquitetura). Três princípios guiam o desenho:

- o banco original nunca muda;
- o que é verificável por regra fica no código, o que exige leitura fica com o modelo, e os dois são testados;
- o único estado é a sessão em memória.

| Decisão | Escolhido | Descartado | Por quê |
|---|---|---|---|
| Consulta | 3 ferramentas de domínio e SQL protegido | só gerar SQL | armadilhas de grafia (168 × 190) |
| Contexto | dossiê inteiro no contexto | RAG | o dossiê cabe; o maior documento tem 2.589 caracteres |
| Orquestração | laço explícito, sem framework | framework de agentes; fluxo fixo | o framework esconde o laço; o fluxo fixo não é autônomo |
| Modelo | DeepSeek V4.1 Flash com `high` | V4 Flash, V4 Pro, Gemini; `max` | decisões 1 e 2 |
| Cliente | httpx próprio | SDK `openai` | decisão 6 |
| Linguagem | Python | Go | decisão 4 |
| Interface | FastAPI, SSE, HTML/JS sem build | Chainlit; Next.js | decisão 5 |
| Erro do modelo | selos que marcam | reescrita automática | decisão 8 |
| SQL do modelo | cópia em memória só com as visões | authorizer sobre o banco original; banco em memória com cache compartilhado | o authorizer era contornável (Parte 3); o próprio SQLite desaconselha o cache compartilhado |
| Estado | sessão em memória | Redis ou PostgreSQL | protótipo local; ver pergunta 5 |

### 2. Como o agente decide o que consultar e o que acontece quando erra

**Como decide.**

- O prompt de sistema (`app/agente/prompt.md`) descreve as três ferramentas e quando usar cada uma. Também descreve
  as seis visões e suas peculiaridades.
- A cada turno, o laço acrescenta a linha "Processo em foco: <número> (<classe>, <situação>)", ou "nenhum". Uma
  pergunta sem número usa o processo em foco. Sem foco, o agente pede o número em vez de chamar uma ferramenta sem
  argumento.
- O número do processo é aceito com ou sem pontuação e validado pelo dígito verificador (módulo 97). Dígito errado,
  formato inválido e número válido mas inexistente dão três mensagens diferentes.
- Quando o foco muda, o dossiê anterior é resumido no histórico ("[dossiê de <número> omitido; …]"), e a interface
  mostra o novo processo em foco.

**Limites.**

- No máximo 8 passos por pergunta e 10 chamadas de ferramenta por passo.
- SQL com um comando por vez, timeout de 5 s e até 50 linhas.
- Os argumentos que o modelo manda são filtrados pelo esquema de cada ferramenta.

**Quando erra.**

- **Erro de ferramenta.** Volta ao modelo como texto em português para ele corrigir dentro do limite de passos. Por
  exemplo, o SQL negado lista as visões permitidas. Se estourar os 8 passos, a resposta diz que não concluiu e lista
  as consultas feitas.
- **Erro do provedor.** O cliente faz 3 tentativas com espera crescente em 429 e 5xx, só antes do primeiro evento da
  resposta. O OpenRouter troca de provedor e, se preciso, usa o modelo reserva. O timeout de 180 s é por leitura do
  stream, não para a chamada inteira: cada trecho recebido reinicia a contagem, e uma minuta legitimamente passa
  disso. Se a conexão cair no meio da resposta, o histórico fica íntegro e a próxima pergunta na mesma conversa
  funciona. Isso foi verificado ao vivo na revisão da API.
- **Erro de conteúdo.** Os selos da decisão 8 apontam o problema, e a faixa da minuta é posta pela interface.

**Avaliações.** São 25 casos, 16 deles críticos. Os gabaritos de todos os casos são conferidos no banco por um teste
que roda sem API. A pontuação tem três camadas:

1. checagens objetivas: fatos esperados, ferramentas usadas, selos esperados e selos proibidos;
2. LLM-juiz com rubrica: fidelidade, limites e utilidade, de 0 a 2;
3. relatório com todas as respostas, para leitura humana.

| Rodada (24/09/2026) | 15:27 | 15:59 | 16:47 |
|---|---|---|---|
| Checagens objetivas, na época | 23/25 | 24/25 | 25/25 |
| Casos críticos, na época | 14/16 | 15/16 | 16/16 |
| Juiz: fidelidade (média de 0 a 2) | 1,80 | 1,64 | 1,68 |
| Juiz: limites | 1,96 | 1,88 | 1,96 |
| Juiz: utilidade | 1,88 | 1,96 | 1,96 |
| Alertas dos selos na época (28 turnos) | 20 | 18 | 7 |
| Alertas com o verificador de hoje (`evals/reverificar.py`) | 2 | 7 | 4 |
| Latência mediana por turno | 12,6 s | 14,1 s | 11,7 s |
| Custo (agente + juiz) | US$ 0,1624 | US$ 0,1795 | US$ 0,1752 |

Os relatórios gravados em `evals/resultados/*.md` mostram os selos como eram na época. Os números de hoje saem de
`uv run python -m evals.reverificar evals/resultados/<rodada>.json`, que não chama o modelo.

O que cada rodada revelou:

- **1ª rodada.**
  - O C03 falhou porque o modelo citou um período de movimentações num só marcador
    (`[Mov 2022-10-11 a 2024-08-15]`), que o verificador não reconhecia. Agora o período vale se as duas pontas
    foram lidas, e o prompt documenta essa forma.
  - O C08 falhou por falso positivo do verificador: uma menção ao magistrado numa seção final de limites virou
    "assinatura". Agora a assinatura exige o nome numa linha curta ou junto do cargo.
  - No C21, o juiz deu fidelidade 0 porque a janela de dados que ele recebia cortava as partes do processo. A janela
    passou a pegar o começo de cada resultado.
  - Com o verificador de hoje, dos 20 alertas da época restam 2, ambos verdadeiros: um `[Mov ...]` sem data (C02) e
    um `[SQL]` marcado para um resultado de `obter_dossie` (C11).
- **2ª rodada.** O único crítico que falhou (C10) era falso positivo do verificador. A resposta recusou redigir a
  minuta de um processo já julgado e citou a sentença existente com reticências. A citação foi lida como decisão de
  mérito. Outras aspas deram alerta por três motivos:
  - erro de pareamento: o regex recomeçava na aspa de fechamento e pegava o texto entre duas citações;
  - eco da pergunta do usuário;
  - citação do texto da própria ferramenta ("Processo não encontrado no banco").

  Depois das correções da integração 3, os alertas da rodada caíram de 18 para 10. Na época, os 10 foram
  classificados como verdadeiros. A releitura para esta documentação mostrou que 3 deles, de norma ("art. 40"), eram
  falsos positivos, corrigidos na Ruling 34. Com o verificador de hoje restam 7, todos verdadeiros.
- **3ª rodada.** 25 de 25 casos e 16 de 16 críticos. Dos 7 alertas da época, os 3 de norma foram classificados como
  verdadeiros. A releitura para esta documentação mostrou que eram falsos positivos, corrigidos na Ruling 34: dois
  "art. 40" vinham da movimentação, e o "art. 485" estava marcado com "[verificar — …]". Os 4 que restam são
  verdadeiros:
  - "do" omitido entre aspas (C23 e C24): "fato, dano e nexo de causalidade", onde o documento diz "do fato, do dano
    e do nexo de causalidade";
  - o campo da ferramenta citado entre aspas como "polo_inferido: ativo" (C21);
  - uma autocitação do modelo entre aspas (C05).

Nenhum gabarito foi alterado, e nenhuma regra do prompt foi afrouxada para um caso passar. O prompt só ganhou a
forma de período de movimentações, que o verificador passou a aceitar. As demais correções foram no verificador e no
juiz, com testes que falham no código antigo.

**Leitura honesta das notas do juiz.**

- A média de fidelidade oscila entre rodadas (1,80, 1,64 e 1,68) porque o mesmo modelo dá respostas diferentes. O
  juiz não vê os selos, então as correções do verificador não mexem nessa nota.
- Na 2ª rodada, o juiz pegou um erro real do agente que os selos não pegariam. Na contagem de julgados em Joinville,
  a resposta deu o número certo (190), mas acrescentou, sem consulta, como se distribuíam os demais processos (C06,
  fidelidade 0).
- Na 3ª rodada, as duas notas 0 (C03 e C23) vieram da frase "63% dos processos do banco não têm documentos". O número
  é verdadeiro (6.309 de 10.000), mas vem do prompt de sistema, que o juiz não vê. A regra 1 do prompt manda usar só
  o que as ferramentas devolvem, e o próprio prompt entrega esse número. O conflito ficou como próximo passo
  (pergunta 4).
- **Critério de sucesso da spec.** Os casos críticos a 100% só foram alcançados na 3ª rodada. Para os demais casos, a
  spec pede ao menos 90% de respostas "adequadas", mas a rubrica não define esse corte. Contando como adequado o caso
  sem nenhuma nota 0, os 9 casos não críticos ficaram em 8/9, 9/9 e 8/9 (89%, 100% e 89%). Com o corte mais duro,
  todas as notas iguais a 2, ficaram em 7/9 nas três rodadas.

**Erros reais do agente, achados e corrigidos na construção.** Os de segurança estão na Parte 3.

- **`finish_reason` repetido.** O OpenRouter repete esse campo no último pedaço do streaming, e o parser emitia os
  eventos duas vezes. Visto ao vivo e corrigido com teste (Ruling 12).
- **Histórico quebrado em desconexão.** Uma desconexão no meio de uma ferramenta deixava um pedido de ferramenta sem
  resposta no histórico, e a conversa quebrava de vez com HTTP 400. Agora o pedido e as respostas entram juntos no
  histórico, e o turno interrompido é fechado (Ruling 15).
- **Promessa falsa no prompt.** O prompt prometia ao modelo um aviso no limite de passos que não existia. Foi
  reescrito (Ruling 15).
- **Corrida no SSE.** A auditoria era gravada depois de o cliente receber o fim da resposta. A pergunta seguinte podia
  ser recusada como "em andamento". Agora o app grava e libera a conversa antes dos eventos finais (Ruling 29).
- **SQLite antigo.** Com SQLite 3.31, 13 testes falhavam, e o app só quebraria na primeira consulta SQL do modelo.
  Agora o app verifica a versão na subida (Ruling 30).

### 3. Como a IA foi usada no desenvolvimento

O desenvolvimento foi feito com o Claude Code, e o usuário decidiu design, escopo e prioridades. A sessão principal
conduziu o brainstorming, o spike, a spec e o plano (21 tarefas em TDD). Depois ela atuou como controladora. Antes
de cada tarefa, rodava o código do plano contra o banco. Em seguida, despachava a tarefa a um subagente implementador
escolhido pela complexidade:

- Haiku para transcrever código já escrito;
- Sonnet para tarefas com decisão de desenho;
- Opus para a interface e para estes documentos.

As tarefas 1 a 20 passaram por revisão, e as mais arriscadas, por revisão adversarial ou por teste ao vivo com o
modelo real. As 39 decisões tomadas no caminho ficaram registradas com o achado que motivou cada uma. Da spec ao commit
`707c603` foram 45 commits, 18 deles de correção.

A IA também atrapalhou, em casos concretos:

- um plano que falhava quando rodado;
- aspas curvas perdidas ao redigitar código;
- defeitos no desenho do próprio controlador;
- um teste que não discriminava;
- alertas de segurança falsos;
- alertas de norma classificados como verdadeiros quando eram falsos positivos (a documentação pegou o erro, e o
  código foi corrigido);
- um diário de execução truncado por um script do controlador.

Detalhes e números em [docs/uso-de-ia.md](docs/uso-de-ia.md).

### 4. O que ficou de fora e próximos passos

**Fora do escopo por decisão.**

- Autenticação e controle de acesso por usuário. O desafio aceita localhost sem autenticação.
- Busca semântica entre processos (RAG ou FTS) e OCR.
- Modo de raciocínio `max` para minutas.
- Persistência de sessões em Redis ou PostgreSQL.
- Deploy e infraestrutura de produção.
- Seleção de modelo na interface. A decisão foi usar só o DeepSeek, com reserva automática.
- Reescrita automática de respostas reprovadas pela verificação.

**Limitações conhecidas da verificação.**

- **Normas.** O selo confere o número do artigo, não a lei: "art. 5" do CPC e da Constituição parecem iguais. Um único
  `[verificar]` entre duas referências na mesma linha vale para as duas.
- **Eco da pergunta.** Aspas que só repetem a pergunta do usuário não são conferidas, nem aprovadas nem alertadas.
  Aprovar daria o selo "literal" a uma citação plantada. Mas, se o usuário plantar uma citação e o modelo atribuí-la a
  um documento, o selo de aspas não pega (Ruling 29).
- **SELECT com texto literal.** Um `select 'qualquer texto'` entra no texto das ferramentas, contra o qual as aspas
  e as normas são conferidas. É um caminho para "lavar" um trecho ou uma norma.
- **Aspas equivalentes.** Na conferência de aspas, apóstrofo e aspas simples, duplas ou curvas contam como o mesmo
  caractere (Ruling 35). Isso não cria um literal falso com palavra diferente.
- **Dispositivo com reticências.** A detecção não reconhece "julgo ... procedente" com reticências ou palavras no meio.
- **Decisões preliminares também alertam.** A checagem do dispositivo reconhece "condeno", "decreto", "acolho", "rejeito" e
  "homologo" em primeira pessoa; por isso "rejeito a preliminar de incompetência", numa fundamentação, também gera o alerta
  de decisão. Aceito: decidir, inclusive uma preliminar, cabe ao magistrado.
- **Dispositivo da própria sentença.** O modelo pode citar entre aspas o dispositivo da sentença que o processo já
  tem, como se fosse a decisão proposta. O selo "o processo já tem sentença e a minuta não avisa" continua valendo.
- **Formatos não detectados.** Número de processo sem pontuação e CPF com espaços, dentro da resposta.
- **Modo minuta por engano.** "modelo de sentença" numa frase referencial ativa o modo minuta. A faixa aparece, e os
  selos ficam ok.
- **`[SQL]` sem sucesso.** O selo de citação aceita `[SQL]` sempre que o turno chamou a ferramenta de consulta, mesmo
  que o SELECT tenha falhado ou sido recusado (por exemplo, por tentar ler uma tabela base).
- **Formas de citação não conferidas.** Aspas simples de abertura ou «», bloco de citação, trechos entre reticências
  com menos de 15 caracteres, e as formas `[Doc. nº N]` e `[Documento N]`.
- **Aviso da minuta só no fim.** A faixa vermelha só aparece depois da verificação, isto é, quando a resposta termina
  de chegar; durante o streaming de uma minuta, o texto aparece antes do aviso.

**Limitações de memória, desempenho e ambiente.**

- **Memória por conversa sem teto.** O que as ferramentas mostraram (documentos lidos e texto das ferramentas) fica
  guardado na conversa. O único limite é o de 1.000 sessões em memória, que descarta a usada há mais tempo.
- **Teto de CPFs por conversa.** Os até 20 CPFs aceitos na busca (Parte 3) valem por conversa: uma conversa nova
  recomeça a contagem do zero. Em produção, com clientes reais, o limite deveria ser por cliente, não por sessão.
- **Concorrência.** Uma consulta pesada com a função Python `normalizar` segura o GIL. As ferramentas de um mesmo
  passo rodam em sequência.
- **Sessões voláteis.** Reiniciar o servidor apaga as conversas, e recarregar a página não restaura o histórico na
  tela.
- **Cabeçalho restaurado sem a sessão.** O navegador guarda o processo em foco e reexibe o cabeçalho ao recarregar a
  página, mesmo que o servidor tenha reiniciado e a sessão em memória já não exista.
- **SQLite 3.36 ou mais novo,** por causa da VFS `memdb`. A alternativa descartada foi um banco em memória com cache
  compartilhado, modo que o próprio SQLite desaconselha.
- **Dependência de teste.** A cadeia de suprimentos do httpx2 foi verificada (Parte 3).

**Limitações da avaliação e da operação.**

- **Avaliação pequena.** São 25 casos, com uma rodada por configuração, e as notas do juiz oscilam entre rodadas. O
  juiz não vê o prompt, e a estatística de 63% do prompt conflita com a regra de usar só as ferramentas. A
  reverificação sem custo reconfere só os selos; o juiz e as checagens objetivas precisam de uma rodada nova.
- **Aderência a instruções de forma.** No teste ao vivo da API, o modelo ignorou o pedido "em três frases".
- **Teto parcial.** O teto de orçamento conta só o que passa pela API, via log de auditoria. As avaliações ficam de
  fora, e o custo de um stream cortado pela desconexão ou de uma tentativa repetida ao provedor também não entra.
- **Desconexão sem teste na API.** O caminho de desconexão no meio da resposta tem teste no laço do agente e foi
  verificado ao vivo (pergunta 2), mas não tem teste no nível da API.

**Próximos passos, em ordem.**

1. Tirar do prompt a estatística de 63%, ou dar a ela uma fonte consultável, e rodar as avaliações de novo.
2. Conferir normas pelo par artigo e lei, e pôr um teto de memória por conversa.
3. Ampliar as avaliações: mais casos por risco, repetições para medir a variância e calibração do juiz contra revisão
   humana.
4. Autenticação, controle de acesso por processo e sessões persistentes (pergunta 5).
5. Busca por trechos e OCR para processos longos.
6. Modo `max` opcional para minutas, se uma avaliação mostrar ganho.

### 5. O que muda com dados reais, sigilosos e 10.000 vezes mais volume

Dez mil vezes a base atual dá da ordem de 100 milhões de processos. Com dados reais, também é de esperar processos
longos, com peças digitalizadas. Parte do que o protótipo faz já foi desenhada para esse cenário e continua valendo:

- o SQL do modelo nunca toca a tabela base: roda sobre visões mascaradas;
- a busca por CPF só aceita número digitado pelo usuário;
- o log não guarda CPF nem chaves;
- o painel só serve documentos lidos na conversa;
- texto de documento é tratado como dado;
- a verificação marca os erros de forma, e a faixa da minuta é posta pela interface.

O resto muda assim:

| Aspecto | Hoje no protótipo | Com dados reais e 10.000 vezes o volume |
|---|---|---|
| Modelo | DeepSeek V4.1 Flash via OpenRouter, provedores sem treino com dados, fp8 ou mais preciso | o mesmo modelo, que tem pesos abertos, num vLLM on-premises; o cliente já fala esse protocolo e troca pela `LLM_BASE_URL`; se ficar em nuvem, retenção zero (`zdr: true`) ou hospedagem própria |
| Banco | SQLite de 41,8 MB, só leitura, visões temporárias por conexão | PostgreSQL ou réplica de leitura, com as visões curadas como objetos do banco |
| SQL do modelo | cópia em memória só com as visões e CPF mascarado (+35 MB de RAM, 0,18 s na subida) | papel de consulta que só enxerga as visões mascaradas da réplica, com timeout e limite de linhas; a cópia em memória não escala |
| Documentos | dossiê inteiro no contexto | busca por trechos (FTS ou vetorial) e OCR das peças digitalizadas; a verificação de aspas continua conferindo contra os trechos lidos |
| Acesso | localhost sem autenticação | autenticação e controle de acesso por processo (sigilo e segredo de justiça), aplicado nas visões, não no prompt |
| Dados pessoais | CPF mascarado nas visões, no log e na resposta (salvo o que o próprio usuário digitou) | o mesmo, mais política de LGPD (base legal, retenção, direitos do titular) e revisão de outros dados pessoais além do CPF |
| Auditoria | arquivo jsonl local | log central imutável, com retenção definida e acesso por papel |
| Sessões | memória, até 1.000 | Redis ou PostgreSQL, sem mudar o resto |
| Avaliação | 25 casos sintéticos | conjunto curado com a área usuária, revisão humana das minutas e avaliação a cada mudança de prompt ou de modelo |

Nas avaliações, uma contagem custou cerca de US$ 0,0006 e uma minuta, cerca de US$ 0,007. Em hospedagem própria, esse
custo vira infraestrutura (GPU), e a latência passa a depender dela.

## Parte 3: segurança, o que as revisões encontraram

Além da revisão de cada tarefa, houve revisões adversariais, testes ao vivo e revisões automáticas de segurança dos
commits. Estes são os achados reais e como foram fechados:

| Achado | Como apareceu | Como foi fechado |
|---|---|---|
| O SQL do modelo contornava o authorizer por CTE: `with x as (select documento from parte) …` devolvia o CPF completo | o controlador rodou o código do plano contra o banco antes da tarefa | o SQL do modelo roda numa cópia em memória só com as 6 visões, com o CPF já mascarado e sem tabela base. A conexão é só leitura, com `query_only`, ATTACH desligado, authorizer (SELECT, READ, FUNCTION e RECURSIVE), timeout de 5 s e limites de tamanho (Ruling 9). Há testes com as consultas do ataque |
| Oráculo de CPF: com cerca de 100 buscas, a máscara deixava recuperar 3 de 3 CPFs reais | revisão adversarial | a busca por CPF só aceita número que o próprio usuário digitou. O laço preenche essa lista, que fica fora do esquema da ferramenta, com até 20 CPFs por conversa. Os argumentos do modelo são filtrados, para ele não se autoautorizar (Rulings 10 e 14) |
| Máscara de CPF que deixava passar valor fora do padrão, e import das visões que falhava aberto | revisão automática de segurança | máscara fail-closed e import direto (Rulings 5 e 6) |
| Limpeza do log: chaves de dicionário e objetos escapavam, e só chaves no formato `sk-…` eram removidas | revisão automática de segurança | limpeza recursiva que remove `Bearer …` e o valor real das variáveis de chave (Ruling 21) |
| O mascaramento de CPF do log corrompia ids de sessão hexadecimais: 11 dígitos seguidos, em cerca de 2% a 5% das sessões | o implementador, investigando um teste intermitente | id de sessão só com letras. O campo não foi isentado da máscara, porque vem do cliente (Ruling 31) |
| Minuta que falhava aberta: a isenção de "decisão de mérito" para trechos entre aspas usava documentos de qualquer processo da conversa, e "procedente" casava dentro de "improcedente" com selo ok | revisão automática dos commits, reproduzida pelo controlador | a isenção vale só para a sentença do processo em foco, e os trechos casam palavras inteiras. Três testes falham no código antigo. Reverificadas as respostas reais das três rodadas, nenhum alerta mudou (Ruling 32) |
| Memória sem limite: o SQL do modelo aceitava valores gigantes (`randomblob`), e o app guardava sessão para qualquer id enviado pelo cliente | revisão adversarial (SQL) e pré-voo do controlador (sessões) | teto de 1 MB por valor no SQLite, de 4.000 caracteres por célula devolvida e de 60 mil por resultado; id validado e teto de 1.000 sessões (Rulings 10 e 13) |
| Varredura de documentos por id: autorizar por "processo consultado" abriria a varredura, porque a busca e o SQL também registram processos | o controlador, ao preparar a rota de documentos | a rota só serve documento lido nesta conversa. Documento inexistente e documento fora da conversa dão o mesmo 403 (Ruling 22) |
| O httpx2, dependência de teste, foi marcado três vezes como possível typosquat | revisões automáticas de segurança | falso positivo, verificado (detalhes abaixo). O pacote fica só no grupo de desenvolvimento; o cliente do produto usa httpx 0.28 |

Também há medidas preventivas de desenho, sem achado associado:

- a resposta do modelo passa pelo DOMPurify antes de virar HTML: o único `innerHTML` do app é `DOMPurify.sanitize(...)`
  na mesma linha, e um teste confere isso;
- a CSP proíbe script inline, e as bibliotecas são servidas localmente;
- o texto dos documentos é tratado como dado.

A verificação do httpx2 conferiu cinco pontos:

- os metadados oficiais do Starlette 1.7.0 exigem o `httpx2` e dizem que o cliente de teste é construído sobre ele;
- o repositório é da organização Pydantic, com a tag da versão publicada no PyPI;
- o hash do wheel no `uv.lock` é o mesmo publicado no PyPI;
- uma varredura do código instalado não achou exec, eval, decodificação base64, subprocess nem hosts fora de exemplos
  de documentação;
- não há atestação de proveniência no PyPI, o que é inconclusivo e comum.
