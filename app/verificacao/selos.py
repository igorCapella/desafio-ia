from app.agente.sessao import Sessao
from app.verificacao.aspas import verificar_aspas
from app.verificacao.citacoes import verificar_citacoes
from app.verificacao.dados_pessoais import verificar_dados_pessoais
from app.verificacao.minuta import eh_minuta, verificar_minuta
from app.verificacao.normas import verificar_normas
from app.verificacao.processo import RX_CNJ, verificar_processo_foco


def verificar(resposta: str, pergunta: str, sessao: Sessao, *, houve_sql: bool,
              mascarar_cpf: bool = True) -> dict:
    """Confere a forma da resposta contra as fontes lidas na conversa (spec §6)."""
    selos: list[dict] = []
    selos += verificar_citacoes(resposta, sessao.docs_vistos, sessao.movs_vistas, houve_sql)
    selos += verificar_aspas(resposta, sessao.docs_vistos, sessao.textos_das_ferramentas,
                             sessao.perguntas)
    selos += verificar_normas(resposta, sessao.docs_vistos, sessao.textos_das_ferramentas)
    conhecidos = sessao.processos_consultados | set(RX_CNJ.findall(pergunta or ""))
    selos += verificar_processo_foco(resposta, sessao.processo_em_foco, conhecidos)
    selos += verificar_dados_pessoais(resposta, mascarar_cpf, sessao.cpfs_do_usuario)
    minuta = eh_minuta(resposta, pergunta)
    if minuta:
        foco = sessao.resumos.get(sessao.processo_em_foco or "", {})
        ja_julgado = (bool(foco.get("sentencas")) or foco.get("data_sentenca") is not None
                      or foco.get("situacao") == "Julgado")
        selos += verificar_minuta(resposta, magistrado=foco.get("magistrado"),
                                  n_documentos=foco.get("n_documentos"), ja_julgado=ja_julgado,
                                  sentencas=foco.get("sentencas", []), docs=sessao.docs_vistos)
    return {"selos": selos, "eh_minuta": minuta}
