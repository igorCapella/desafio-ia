# Uso de IA no desenvolvimento

Este documento conta como o protótipo foi construído com IA. Mostra que modelo fez o quê, como o trabalho foi
conferido e onde a IA atrapalhou. Os números vêm de quatro fontes:

- o histórico do git;
- os relatórios de cada tarefa;
- as rodadas de avaliação gravadas em `evals/resultados/` e a reverificação delas com `evals/reverificar.py`;
- o diário de execução, que registrou cada decisão tomada no caminho com o achado que a motivou. As decisões são
  citadas como "Ruling N".

O usuário decidiu o design, o escopo e as prioridades. A IA propôs, escreveu, revisou e testou.

## Em números

| Item | Valor |
|---|---|
| Linha do tempo | spec em 23/09/2026, 18:47; plano em 24/09, 09:23; último commit da implementação antes da documentação (`c567b16`) em 24/09, 18:23; primeira versão destes documentos (`0c088c1`) às 18:55; reverificação reproduzível (`eb545cf`) às 19:06 |
| Tarefas do plano | 21, em TDD. As tarefas 10 a 14 foram executadas como um lote. Depois vieram 3 rodadas de integração guiadas por dados reais, 1 correção de segurança, 1 revisão conjunta e, já durante a documentação, 2 correções do verificador (Rulings 34 e 35) |
| Decisões registradas | 39 (Ruling 1 a 39) |
| Commits | 45 da spec ao `eb545cf`, 18 deles de correção (`fix`) |
| Rodadas de correção pedidas pela revisão das tarefas | 9, todas encerradas sem pendência aberta: tarefas 2, 3, 6, 7, 8 e 9, lote 10–14 (duas rodadas) e tarefa 15 |
| Testes | 210 no pytest (204 em `tests/` e 6 em `evals/`) e 9 do núcleo JavaScript no Node |
| Rodadas reais de avaliação | 3, com 25 casos cada |
| Falsos positivos do verificador achados na releitura para esta documentação e na reclassificação que ela motivou | 9 alertas nas três rodadas (Rulings 34 e 35), corrigidos no código e reverificados |
| Custo de API registrado (OpenRouter) | cerca de US$ 0,65, de uma chave com limite de US$ 4 (detalhe no fim) |
| Custo do Claude Code | não medido nas fontes deste documento |

## Ferramentas

- **Claude Code**, com as skills do pacote superpowers:
  - *brainstorming* com companheiro visual. Os mockups de `docs/superpowers/specs/mockups/` saíram daí, e o usuário
    aprovou o layout A;
  - spike de modelos com código descartável (`docs/pesquisa/2026-09-23-spike-modelos/codigo-descartavel/`);
  - *writing-plans*, que produziu o plano em 21 tarefas com o código de cada passo;
  - *subagent-driven development*: um controlador despacha cada tarefa a um subagente implementador e depois a um
    revisor, e registra as decisões no diário;
  - TDD, revisões adversariais e testes ao vivo com o modelo real.
- **Revisão automática de segurança dos commits.** Os achados reais estão nas Rulings 5, 6, 21 e 32. Os falsos
  positivos sobre o httpx2 estão descritos abaixo.
- **Context7**, para consultar a documentação atual das bibliotecas.
- **Memória do Claude Code**, com regras que valem entre sessões. Exemplos: o IPv6 quebrado da máquina e as
  decisões do desafio.
- **Instruções configuradas.** O [CLAUDE.md](../CLAUDE.md) guarda as convenções do projeto. O prompt do agente
  (`app/agente/prompt.md`) é versionado, porque é parte do produto.

## Que modelo fez o quê

| Papel | Modelo | Evidência |
|---|---|---|
| Design: brainstorming, spike e spec | Claude Opus 5.5 | commits `0ce83a5` e `62e8a85` |
| Plano, e controlador das tarefas 1 e 2 | Claude Opus 4.8 | commit `bdbd02f` e diário |
| Controlador da tarefa 3 em diante | Claude Opus 5.5 | diário |
| Implementação | Haiku 4.5, Sonnet 5 ou Opus 5.5, conforme a complexidade | trailers `Co-Authored-By` dos commits |
| Revisão | Sonnet por padrão; Opus nas revisões adversariais (tarefas 6 e 9) e na revisão final, prevista para depois destes documentos; Haiku nas mais simples (tarefas 15 e 17, integração 1) | diário |

A implementação foi dividida assim:

| Implementador | Trabalho | Commits |
|---|---|---|
| Haiku 4.5 | tarefas com o código já escrito no plano ou no adendo: 4, 5, 7, 8, lote 10–14, 15, 17 e 20; integração 1; correção de segurança; correção da revisão conjunta; correções das Rulings 34 e 35 | 24 |
| Sonnet 5 | tarefas com decisão de desenho: 6 (ferramentas e SQL protegido), 9 (laço e prompt), 16 (API), 19 (avaliações); integrações 2 e 3 | 9 |
| Opus 5.5 | tarefa 18 (a interface da demo) e tarefa 21 (estes documentos e o `evals/reverificar.py`) | 3 até o `eb545cf`: 1 da tarefa 18 e 2 da tarefa 21 |

Os 45 commits até o `eb545cf` somam 24 com trailer do Haiku 4.5, 9 do Sonnet 5, 7 do Opus 5.5 e 5 do Opus 4.8. Nas
tarefas 1 a 3, o trailer registra o modelo do controlador, não o do subagente. A regra de registrar o modelo de quem
fez o commit veio com a Ruling 7.

## O fluxo

1. **Brainstorming.** Conversa com o usuário e mockups no companheiro visual. O usuário aprovou cada seção do design e
   o layout A.
2. **Spike.** Foram comparados 4 modelos em 9 turnos, com revisão manual de todas as respostas (ver
   [RESULTADOS.md](pesquisa/2026-09-23-spike-modelos/RESULTADOS.md)).
3. **Spec e plano.** A spec registra o design aprovado. O plano tem 21 tarefas em TDD, cada passo com código.
4. **Cada tarefa:**
   1. *Pré-voo.* O controlador roda o código do plano contra o banco real.
   2. *Adendo.* O controlador escreve um adendo com o código exato já corrigido. Depois do caso das aspas curvas
      (abaixo), os blocos passaram a ser copiados por script, e as últimas correções já vieram com um script
      validado pelo controlador.
   3. *Implementação.* O teste vem primeiro e precisa falhar (RED). Depois vem o código (GREEN) e roda a suíte
      inteira.
   4. *Revisão.* Confere conformidade com a spec e qualidade. Nas tarefas de risco, a revisão é adversarial ou inclui
      teste ao vivo com o modelo real.
   5. *Correção.* Uma nova rodada acontece quando a revisão acha algo importante ou crítico.
   6. *Registro.* A decisão vai para o diário, com o achado que a motivou e o custo se ela estiver errada.
5. **Integrações guiadas por dados reais.** O log da revisão ao vivo e as três rodadas de avaliação viraram
   correções, cada uma com teste. O efeito de cada mudança no verificador é medido reverificando as respostas
   gravadas (`evals/reverificar.py`), sem chamar o modelo.
6. **Revisão conjunta e revisão final.** A revisão final, com Opus, vem depois destes documentos.

## Onde a IA atrapalhou

### No design

- **Comarca interpretada errado.** O primeiro perfil dos dados contou "1.024 processos com comarca divergente da
  unidade". Eram diferenças de grafia, não divergência real: o campo tem 230 grafias para 60 comarcas (o relatório do spike
  chegou a registrar 104, errado; a revisão da documentação conferiu no banco). Com a leitura
  certa, a comarca passou a vir da unidade.
- **Mockup com advogados no lugar das partes.** Um mockup da interface trouxe os advogados onde deviam estar as
  partes.
- **Falsos negativos das checagens por palavra-chave.** No spike, as checagens automáticas marcaram como erradas 4
  respostas que a leitura mostrou certas, e pegaram só 1 falha real. Por isso as avaliações do produto usam rubrica,
  LLM-juiz e leitura humana, com as checagens como primeiro filtro.
- **Súmula inventada.** O DeepSeek V4 Flash inventou o texto da Súmula 403 do STJ. A súmula real trata de publicação
  não autorizada de imagem. Isso ajudou a descartar esse modelo e deu origem à regra do `[verificar]` no prompt e à
  verificação de normas.

### Nesta implementação

- **Defeitos do plano que só apareceram rodando o código.** O plano foi escrito por IA com o código de cada passo, e
  parte desse código não funcionava:
  - um teste falharia por causa de uma palavra: exigia "assinad" num texto que diz "assinatura" (Ruling 8);
  - o authorizer do SQL era contornável por CTE e devolvia o CPF completo. Além disso, no SQLite 3.53 o `count(*)`
    era negado, e a busca por CPF nunca casava, porque comparava com a visão mascarada (Ruling 9);
  - o código de verificação quebraria com `TypeError` contra a estrutura real da sessão (Ruling 16);
  - o SSE do FastAPI era usado de um jeito que quebrava e codificava o JSON duas vezes (Ruling 19);
  - o resumo do log lia `latencia` quando o log grava `latencia_ms`, o que daria p50 e p95 iguais a zero (Ruling 25).

  A resposta foi o pré-voo: antes de cada tarefa, o controlador roda o código do plano contra o banco real e entrega
  um adendo corrigido.
- **Aspas curvas perdidas ao redigitar código.** Um implementador transcreveu à mão um bloco que tratava as aspas
  curvas (“ ”). O `.replace` virou uma string entre aspas triplas: Python válido, aparência inofensiva, mas as aspas
  curvas deixaram de ser normalizadas. A revisão pegou o erro (Ruling 17). Desde então, todo bloco de código dos
  adendos é copiado por script, nunca redigitado, e os relatórios conferem os arquivos byte a byte contra o adendo.
- **Defeitos no desenho do próprio controlador.** Os revisores pegaram erros do controlador, não só dos
  implementadores:
  - a verificação da minuta tirava da conferência todo trecho entre aspas, e assim uma decisão inventada entre aspas
    escapava (Ruling 20);
  - "Faça um resumo da sentença" ativava o modo minuta (Ruling 17);
  - pedidos de minuta feitos por substantivo, como "Preciso de uma proposta de sentença", não eram reconhecidos
    (Ruling 20);
  - um script de correção trocou uma regex e deixou desatualizado o comentário logo acima (Ruling 31).
- **Diagnóstico errado de um teste intermitente.** O controlador atribuiu a falha intermitente de um teste de
  auditoria a uma corrida no streaming. O implementador investigou, capturou as variáveis na hora da falha e achou a
  causa real: o mascaramento de CPF do log transformava em "CPF" parte de ids de sessão hexadecimais (Ruling 31).
- **Teste que não discriminava.** O teste do controlador para "aspas dentro de código" já passava antes da correção:
  o valor entre aspas era curto demais para o verificador olhar. O teste foi refeito com o caso real (duas aspas em
  trechos de código diferentes) e com a prova de que falha no código antigo.
- **Alertas de segurança falsos.** A revisão automática marcou três vezes o httpx2, uma dependência de teste, como
  possível typosquat, e uma dessas vezes como risco alto. A verificação conferiu os metadados do Starlette, o
  repositório, o hash do lock e o código instalado, e concluiu que era falso positivo (detalhes no
  [DECISOES.md](../DECISOES.md), Parte 3). Levar o alerta a sério custou tempo; ignorá-lo sem conferir seria pior.
- **Alertas classificados errado.** O controlador classificou como verdadeiros, em duas rulings (29 e 33), os
  alertas de norma "art. 40", como "norma citada de memória". O relatório da integração 3 fez o mesmo. Relendo as
  respostas para escrever estes documentos, apareceu a causa real. A norma está na descrição de uma movimentação
  lida, "Arquivamento Provisório (art. 40 LEF)", e o verificador só procurava nos documentos. Um alerta de "art. 485"
  também era falso: o modelo tinha marcado a norma com uma variante da marca `[verificar]`. O código foi corrigido
  (Ruling 34). Ao reclassificar os alertas restantes, o controlador achou mais um falso positivo: uma citação literal
  de um alerta da ferramenta, com aspas internas (Ruling 35). Depois, todas as respostas gravadas das três rodadas
  (25 casos por rodada, 84 turnos no total) foram reverificadas com um script que agora está no repositório,
  `evals/reverificar.py`. Os alertas caíram de 20, 18 e 7 na época para 2, 7 e 4, e os 13 que restam são verdadeiros
  ([DECISOES.md](../DECISOES.md), decisão 8).
- **O LLM-juiz também erra.** Na primeira rodada, o juiz deu fidelidade 0 a uma resposta que citava uma parte real
  do processo, porque a janela de dados que recebia cortava as partes. O defeito era do arcabouço de avaliação. Na
  terceira rodada, o juiz deu 0 a duas respostas por causa de uma estatística verdadeira que vem do prompt, que ele
  não vê.
- **O classificador de segurança do modelo interrompeu a sessão.** O classificador do Claude Opus 5.5 interrompeu o
  trabalho enquanto a sessão reprocessava as transcrições do spike. A sessão seguiu com o Claude Opus 4.8, que fez o
  plano e as tarefas 1 e 2, e voltou ao Opus 5.5 depois de compactar o contexto.
- **Diário de execução truncado.** Os scripts do controlador que inseriam novas decisões no diário gravavam só o
  trecho até o ponto de inserção e a decisão nova; o resto do arquivo se perdia. Por um tempo sumiram o progresso de
  cada tarefa, as notas e o ponto de retomada. O arquivo foi reconstruído repetindo o histórico de edições
  registrado na transcrição da sessão, e depois conferido linha a linha contra a cópia truncada. Desde então, toda
  inserção confere se o tamanho novo é o antigo mais o trecho inserido.

### O que funcionou como defesa

- Rodar o código antes de confiar nele: pré-voo e testes ao vivo.
- Revisão por outro agente em cada tarefa, adversarial nas tarefas de risco.
- Cópia de código por script, conferida byte a byte.
- Dados reais como fonte de verdade: o log ao vivo e as rodadas de avaliação acharam problemas que os testes
  sintéticos não pegavam.
- Registrar cada decisão com o achado que a motivou e o custo se ela estiver errada.

## Custo de API registrado

| Etapa | Custo | Fonte |
|---|---|---|
| Spike: bateria dos 4 modelos | US$ 0,058 | soma da tabela do RESULTADOS.md |
| Spike: teste `high` × `max` | US$ 0,046 | RESULTADOS.md |
| Teste ao vivo do cliente LLM (revisão da tarefa 7) | US$ 0,00027 | diário |
| Teste ao vivo do agente (revisão da tarefa 9) | US$ 0,0105 | diário |
| Testes ao vivo pela API e pela interface (revisões das tarefas 16 e 18) | US$ 0,0200 | log de auditoria |
| Três rodadas de avaliação (agente e juiz) | US$ 0,5171 | `evals/resultados/` |
| **Total registrado** | **cerca de US$ 0,65** | |

São os valores registrados nas fontes do projeto. A reverificação das respostas gravadas não chama o modelo e não
tem custo. As sondagens de provedores feitas no spike não têm custo registrado. O painel do OpenRouter é a fonte
definitiva e não foi consultado para este documento. O custo do próprio Claude Code, isto é, dos modelos que
escreveram e revisaram o código, não foi medido.
