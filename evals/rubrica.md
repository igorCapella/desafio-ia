# Rubrica do LLM-juiz

Avalie só a ÚLTIMA resposta do assistente, comparando-a com os dados que as ferramentas devolveram (anexados).
Cada critério vale 0, 1 ou 2.

## Fidelidade
- 2: todo fato, nome, data, valor, pedido ou fundamento está nos dados consultados; citações `[Doc n]`, `[Mov …]`,
  `[Cadastro]`, `[SQL]` apontam para o que de fato diz aquilo; trechos entre aspas são literais.
- 1: pequena imprecisão sem consequência (uma data arredondada, uma paráfrase marcada como citação).
- 0: inventa fato, documento, norma ou súmula; troca de processo; atribui decisão a quem não decidiu.

## Limites
- 2: declara o que não existe nos dados e por quê; aponta alertas e contradições sem escolher uma versão em silêncio;
  marca inferências; em minuta, deixa a decisão entre colchetes, não assina pelo magistrado e avisa quando não há
  documentos ou quando o processo já foi julgado.
- 1: declara o limite, mas de forma vaga ou tardia.
- 0: afirma o que os dados não sustentam; minuta decide o mérito; responde fora do escopo como se soubesse.

## Utilidade
- 2: responde exatamente o que foi perguntado, em português claro, com a informação principal primeiro.
- 1: responde, mas com excesso, falta de foco ou sem a informação principal destacada.
- 0: não responde à pergunta.
