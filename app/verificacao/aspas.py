import re

_RX_ASPAS = re.compile(r'[“"]([^”"\n]{20,}?)[”"]')


def normalizar_trecho(s: str) -> str:
    s = re.sub(r"[*_`]", "", s).lower().replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip(" .,;:")


def verificar_aspas(resposta: str, docs: dict[int, str]) -> list[dict]:
    textos = {i: normalizar_trecho(t or "") for i, t in docs.items()}
    literais, fontes, suspeitos = [], [], []
    for trecho in _RX_ASPAS.findall(resposta):
        frags = [normalizar_trecho(x) for x in re.split(r"\.\.\.|…|\[\.\.\.\]", trecho)
                 if len(normalizar_trecho(x)) >= 15]
        if not frags:
            continue
        # Todos os fragmentos (separados por reticências) têm de estar no MESMO documento.
        doc = next((i for i, t in textos.items() if all(f in t for f in frags)), None)
        if doc is None:
            suspeitos.append(trecho[:120])
        else:
            literais.append(trecho[:120])
            fontes.append(doc)
    selos = []
    if literais:
        # "docs" diz de onde veio cada trecho: a interface abre o documento no ponto citado.
        selos.append({"tipo": "aspas", "status": "ok",
                      "mensagem": f"{len(literais)} trecho(s) entre aspas conferido(s) como literal(is).",
                      "trechos": literais, "docs": fontes})
    if suspeitos:
        selos.append({"tipo": "aspas", "status": "alerta",
                      "mensagem": "Trecho entre aspas não encontrado literalmente nos documentos "
                                  "(pode ser paráfrase).", "trechos": suspeitos})
    return selos
