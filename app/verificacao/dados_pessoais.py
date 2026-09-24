import re

from app.dados.conexao import py_mascarar_cpf

_RX_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")


def verificar_dados_pessoais(resposta: str, mascarar_cpf: bool,
                             cpfs_do_usuario: set[str] = frozenset()) -> list[dict]:
    # Proteção extra (spec §6): a camada de dados já mascara; aqui só se confere a resposta.
    if not mascarar_cpf:
        return []
    vazados = [c for c in _RX_CPF.findall(resposta)
               if re.sub(r"\D", "", c) not in cpfs_do_usuario]
    if not vazados:
        return []
    return [{"tipo": "dados_pessoais", "status": "alerta",
             "mensagem": "A resposta traz CPF completo, que deveria aparecer mascarado.",
             "trechos": sorted({py_mascarar_cpf(c) for c in vazados})}]
