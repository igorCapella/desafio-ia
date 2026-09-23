# Spike: escolha de modelos (23/09/2026)

> **Descartável.** O código em `codigo-descartavel/` não é do produto; os caminhos apontam para o ambiente do spike. Este diretório existe como evidência para o `DECISOES.md` e para a arguição.

## Pergunta

O DeepSeek V4 **Flash** dá conta das tarefas do desafio ou é preciso o **Pro**? Qual Gemini usar?

## Método

- Agente mínimo com 3 ferramentas: `buscar_processo`, `obter_dossie` (cadastro, partes, advogados, movimentações, íntegra dos documentos e alertas de qualidade) e `consultar_sql` (somente leitura: conexão `mode=ro`, *authorizer* que só permite SELECT, um comando por vez, timeout).
- **Um único cliente** no protocolo de chat compatível com OpenAI, para os dois provedores: OpenRouter e o endpoint OpenAI do Gemini.
- 9 turnos em 6 conversas, cobrindo os 5 requisitos e a minuta. Gabaritos calculados direto no banco.
- Checagens automáticas por palavras-chave e **revisão manual de todas as respostas**.

| # | Pergunta | Mede |
|---|---|---|
| A1–A3 | Resumo; partes/magistrado/advogados/pedidos; julgamento e fundamentos, sobre o processo `0000001-15.2022.8.99.9012`, sem repetir o número após A1 | Consultar, fundamentar, contexto multi-turno, fidelidade (a sentença tem contradições internas) |
| B1 | Minuta de sentença, `0000001-81.2023.8.99.9011` (em andamento, instruído) | Minuta rotulada como proposta, sem inventar |
| C1 | Advogados e pedidos de um processo sem documentos | Reconhecer limites |
| D1 | Magistrado de um processo sem magistrado cadastrado | Reconhecer limites |
| E1 | Quantos processos julgados há em Joinville (gabarito: 190) | SQL autônomo e armadilhas de grafia |
| F1–F2 | Número inexistente; jurisprudência do STJ | Fora do escopo |

## Resultado (após revisão manual)

| Modelo | Tarefas corretas | Contradições do processo 37 | Minuta | Súmulas de fora dos autos | Custo da bateria | Latência média/turno |
|---|---|---|---|---|---|---|
| DeepSeek V4 Flash | 9/9 | ❌ suavizou ("os dados estão consistentes") | ❌ decidiu o mérito | 2, **uma com texto inventado (Súmula 403)** | US$ 0,006 | 16 s |
| **DeepSeek V4.1 Flash** | **9/9** | ✅ as 3 | ✅ dispositivo entre colchetes | 0 | US$ 0,017 | 34 s |
| DeepSeek V4 Pro 0813 | 9/9 | ✅ as 3 | ✅ dispositivo entre colchetes | 0 | US$ 0,035 | 41 s (minuta: 200 s) |
| Gemini 3.5 Flash (grátis) | 6/7 executadas (+2 sem cota) | ✅ as 3 | ❌ decidiu o mérito | 2 (corretas) | US$ 0 | 33 s |

Achados que só a leitura revelou:
- **V4 Flash** inventou o texto da Súmula 403 do STJ. A súmula real trata de publicação não autorizada de imagem. Ele também sugeriu uma faixa de indenização "conforme jurisprudência catarinense", sem fonte, e leu o saneamento como "afastou para análise posterior", suavizando a contradição.
- **Gemini 3.5 Flash** afirmou que a magistrada da unidade "é a responsável" pelo processo sem magistrado vinculado, transformando uma inferência em fato. O V4.1 Flash, com os mesmos dados, deu a informação com ressalva explícita.
- **V4.1 Flash e V4 Pro** deixaram a decisão para o juiz. O V4.1 marcou que a própria petição cita a Súmula 385 de forma incongruente. O V4 Pro e o Gemini acharam a divergência de autoria do Doc 946 e a data divergente da audiência.
- **Checagens por palavras-chave deram 4 falsos negativos** (V4 Flash F1, V4.1 Flash D1, V4 Pro C1 e F2) e só 1 falha real (Gemini D1). A avaliação do produto precisa de rubrica e revisão, não só de regex.

### Fidelidade das citações entre aspas

Trechos entre aspas nas respostas foram conferidos contra o texto das fontes lidas na conversa (checagem local; excluídos falsos positivos da extração). Cerca de 65 trechos no total; **5 não estavam nas fontes**:

| Modelo | Não literais | O quê |
|---|---|---|
| V4 Pro 0813 | 0 de 7 | — |
| V4.1 Flash | 2 de ~39 | paráfrases leves apresentadas como literais ("pleiteia" onde o texto diz "pleiteando") |
| Gemini 3.5 Flash | 1 de ~9 | frase da sentença reescrita entre aspas |
| V4 Flash | 2 de 10 | Súmula 385 citada de memória (texto correto, mas fora dos autos) e **Súmula 403 com texto inventado** |

Implicação: o leitor trata aspas como texto literal, então o produto precisa de um verificador automático de citações.

## Ambiente e infraestrutura

- **Gemini, chave gratuita:** 20 requisições/dia por modelo (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). Pro com cota zero (429). 3.7 Flash, 3.8 Flash e `flash-latest` com 503 (alta demanda) durante todo o teste. `gemini-2.5-pro` indisponível para novos usuários. O plano gratuito também permite ao Google usar os dados enviados.
- **OpenRouter:** chave com limite de US$ 4, expira em 23/10/2026. O spike gastou cerca de US$ 0,06.
- **WSL2 com IPv6 quebrado:** clientes HTTP em Python travam até o timeout, então é preciso forçar IPv4.
- **DeepSeek V4 tem pesos abertos (MIT)** no Hugging Face, em todas as variantes. Com dados sigilosos, o mesmo modelo pode rodar on-premises.
- O protocolo OpenAI-compatível funcionou com tool calling nos dois provedores, inclusive o retorno das *thought signatures* do Gemini em chamadas encadeadas.

### Nível de raciocínio (effort) e roteamento no OpenRouter

- **Níveis reais do DeepSeek V4.1 Flash** (documentação da DeepSeek): `low`, `high` (padrão) e `max`. Os demais nomes são convertidos: `minimal`→low, `medium` e `xhigh`→high, `max`→max. O spike rodou no padrão (`high`).
- **Sem raciocínio o modelo erra conta simples** (`enabled: false` → respondeu 16 em vez de 24). Manter o raciocínio ligado.
- **Filtro de privacidade da conta:** o OpenRouter remove o provedor oficial da DeepSeek ("Paid model training violation (account settings)"). Todas as chamadas vão para provedores terceiros que não treinam com os dados (25 de 26 endpoints). É um bom argumento para dados sigilosos; não afrouxar.
- **Nos terceiros, `max` quase não muda nada.** Em pergunta com resposta verificável, o padrão e o `max` deram de 190 a 380 tokens de raciocínio nos 7 provedores que responderam, e todos acertaram. Esses provedores tratam o nível como teto de orçamento. Falta medir em tarefa difícil (contradições, minuta).
- **O provedor pesa mais que o nível:** o mesmo nível variou de 210 a 1.242 tokens conforme o provedor.
- **Teste `high` × `max` nas tarefas difíceis** (conversas A, B e D; V4.1 Flash fixo no DeepInfra fp8; 2 repetições de cada; US$ 0,046):

| Config | Contradições (de 3) | Minuta decide o mérito? | Súmulas externas | D1 com ressalva | Aspas literais | Raciocínio (tokens) | Latência da minuta | Custo |
|---|---|---|---|---|---|---|---|---|
| high r1 | 3 | não | 0 | sim | 27/28 | 3.482 | 75 s | US$ 0,0077 |
| high r2 | 3 | não | 0 | sim | 17/18 | 2.300 | 63 s | US$ 0,0067 |
| max r1 | 3 | não | 0 | sim | 14/14 | 19.327 | 190 s | US$ 0,0132 |
| max r2 | 3 | não | 0 | sim | 21/21 | 30.773 | 318 s | US$ 0,0185 |

  O DeepInfra respeita o `max` (6 a 10 vezes mais raciocínio), mas os critérios críticos não mudam. As inconsistências finas (autoria do Doc 946, datas da audiência) aparecem nas duas configurações. O ganho é só nas aspas (100% contra cerca de 96% literais), com a minuta 3 a 4 vezes mais lenta. **Decisão: `high` em tudo.** A fidelidade das aspas fica com um verificador determinístico, que é mais barato e mais confiável que raciocínio extra. As duas execuções `high` deram o mesmo resultado nos critérios críticos, o que indica boa reprodutibilidade.
- **Quantização varia por provedor:** há endpoints em fp4 (open-inference, relace, sail-research) e em fp8. No produto, exigir fp8 via `provider.quantizations`, junto com `require_parameters: true`.

## Achados de dados (corrigindo o perfil inicial)

- `processo.comarca` tem 230 grafias para 104 comarcas (caixa, espaços, acentos, abreviações como "S. José"). Os "1.024 processos com comarca divergente da unidade" do perfil inicial eram **grafia**, não divergência real. Usar `unidade.comarca`.
- Processo 357, Doc 946: o autor cadastrado difere da assinatura no texto.
- Processo 357: a data da audiência diverge entre a ata e as movimentações.

## Implicações para o design

1. Cliente único OpenAI-compatível; o provedor vira configuração (URL, chave, modelo).
2. DeepSeek V4.1 Flash como modelo padrão; o Pro não se paga (qualidade parecida, 2 a 6 vezes mais lento).
3. Guarda de citações: súmula ou jurisprudência que não aparece nos autos é marcada como "não verificada".
4. A minuta deixa o dispositivo (procedência ou improcedência) entre colchetes, com regra no prompt e checagem no código.
5. Ferramentas entregam contexto rotulado para inferências, por exemplo "magistrados da unidade, sem vínculo com o processo".
6. Camada de normalização: `situacao`, `comarca`, polo vs. tipo, advogados extraídos de `documento.autor`.
7. Resiliência: retry com backoff e modelo reserva em 429/503; IPv4; controle de orçamento.
8. Streaming na interface, porque a minuta leva de 35 a 200 s.
9. Avaliação com rubrica e revisão humana, com as checagens automáticas como primeiro filtro.
