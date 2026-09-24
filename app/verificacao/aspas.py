import re

_RX_CODIGO = re.compile(r'`{3}.*?`{3}|`[^`\n]*`', re.S)  # código não é citação dos autos
# Aspas pareadas EM ORDEM (curvas “…” ou retas "…"): o texto ENTRE duas citações nunca vira citação.
RX_ENTRE_ASPAS = re.compile(r'“([^”\n]*)”|"([^"\n]*)"')
_RX_RETICENCIAS = re.compile(r"\.\.\.|…|\[\.\.\.\]")
# Texto que o próprio sistema manda escrever (o aviso da minuta) não é citação dos autos.
_TEXTOS_DO_SISTEMA = ("proposta de texto gerada por ia",)
_MIN_CARACTERES = 20


def normalizar_trecho(s: str) -> str:
    s = re.sub(r"[*_`]", "", s).lower().replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def fragmentos(trecho: str) -> list[str]:
    """Partes de um trecho citado separadas por reticências, normalizadas (só as de 15+ caracteres)."""
    return [f for f in (normalizar_trecho(x) for x in _RX_RETICENCIAS.split(trecho)) if len(f) >= 15]


def trechos_entre_aspas(texto: str) -> list[str]:
    return [a or b for a, b in RX_ENTRE_ASPAS.findall(_RX_CODIGO.sub(" ", texto))]


def _linhas_desbalanceadas(texto: str) -> list[str]:
    # Aspas ímpares numa linha (ex.: 12" como polegada) desalinham o pareamento e uma citação adiante
    # ficaria sem conferência nenhuma: melhor avisar do que silenciar.
    return [linha.strip()[:120] for linha in _RX_CODIGO.sub(" ", texto).splitlines()
            if linha.count('"') % 2 or linha.count("“") != linha.count("”")]


def _no_texto(fragmento: str, texto: str) -> bool:
    # Palavras inteiras nas pontas: "procedente o pedido" não é literal de "improcedente o pedido".
    if fragmento not in texto:
        return False
    antes = r"(?<!\w)" if fragmento[0].isalnum() else ""
    depois = r"(?!\w)" if fragmento[-1].isalnum() else ""
    return re.search(antes + re.escape(fragmento) + depois, texto) is not None


def literal_em(frags: list[str], textos: list[str]) -> bool:
    # Todos os fragmentos (separados por reticências) têm de estar no MESMO texto.
    return any(all(_no_texto(f, t) for f in frags) for t in textos)


def verificar_aspas(resposta: str, docs: dict[int, str], textos_ferramentas: list[str] = (),
                    perguntas: list[str] = ()) -> list[dict]:
    # `textos_ferramentas`: o que as ferramentas mostraram além dos documentos (cadastro, "não
    # encontrado", buscas, SQL) — fonte literal. `perguntas`: aspas que só repetem o usuário não são
    # citação dos autos — nem aprovadas (seria selo para citação plantada), nem alertadas.
    textos = {i: normalizar_trecho(t or "") for i, t in docs.items()}
    das_ferramentas = [normalizar_trecho(t) for t in textos_ferramentas if t]
    do_usuario = [normalizar_trecho(t) for t in perguntas if t]
    literais, fontes, de_ferramentas, suspeitos = [], [], [], []
    for trecho in trechos_entre_aspas(resposta):
        frags = fragmentos(trecho)
        if (len(trecho) < _MIN_CARACTERES or not frags
                or any(t in normalizar_trecho(trecho) for t in _TEXTOS_DO_SISTEMA)):
            continue
        doc = next((i for i, t in textos.items() if literal_em(frags, [t])), None)
        if doc is not None:
            literais.append(trecho[:120])
            fontes.append(doc)
        elif literal_em(frags, das_ferramentas):
            de_ferramentas.append(trecho[:120])
        elif not literal_em(frags, do_usuario):
            suspeitos.append(trecho[:120])
    selos = []
    total = len(literais) + len(de_ferramentas)
    if total:
        # "docs" diz de onde veio cada trecho: a interface abre o documento no ponto citado.
        selos.append({"tipo": "aspas", "status": "ok",
                      "mensagem": f"{total} trecho(s) entre aspas conferido(s) como literal(is).",
                      "trechos": literais, "docs": fontes,
                      "trechos_das_ferramentas": de_ferramentas})
    if suspeitos:
        selos.append({"tipo": "aspas", "status": "alerta",
                      "mensagem": "Trecho entre aspas não encontrado literalmente nos documentos "
                                  "(pode ser paráfrase).", "trechos": suspeitos})
    desbalanceadas = _linhas_desbalanceadas(resposta)
    if desbalanceadas:
        selos.append({"tipo": "aspas", "status": "alerta",
                      "mensagem": "Aspas desbalanceadas: algum trecho entre aspas pode não ter sido "
                                  "conferido.", "trechos": desbalanceadas})
    return selos
