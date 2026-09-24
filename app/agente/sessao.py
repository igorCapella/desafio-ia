import re
import uuid
from collections import OrderedDict


class Sessao:
    def __init__(self) -> None:
        self.historico: list[dict] = []
        self.processo_em_foco: str | None = None
        self.foco_resumo: dict = {}
        self.custo_total: float = 0.0

    def adicionar(self, msg: dict) -> None:
        self.historico.append(msg)

    def definir_foco(self, numero: str, resumo: dict) -> None:
        self.processo_em_foco = numero
        self.foco_resumo = resumo

    def linha_de_contexto(self) -> str:
        if not self.processo_em_foco:
            return "Processo em foco: nenhum."
        r = self.foco_resumo
        return (f"Processo em foco: {self.processo_em_foco} "
                f"({r.get('classe', '?')}, {r.get('situacao', '?')}).")

    def compactar_dossies_antigos(self) -> None:
        for m in self.historico:
            num = m.get("_numero")
            if (m.get("role") == "tool" and m.get("name") == "obter_dossie"
                    and num and num != self.processo_em_foco and not m.get("_compactado")):
                m["content"] = (f"[dossiê de {num} omitido para poupar contexto; "
                                f"chame obter_dossie de novo se precisar]")
                m["_compactado"] = True


_RX_ID = re.compile(r"[0-9a-f]{32}")
_MAX_SESSOES = 1000  # sessões em memória; a usada há mais tempo sai primeiro

SESSOES: OrderedDict[str, Sessao] = OrderedDict()


def _guardar(sid: str, sessao: Sessao) -> Sessao:
    SESSOES[sid] = sessao
    while len(SESSOES) > _MAX_SESSOES:
        SESSOES.popitem(last=False)
    return sessao


def nova_sessao() -> str:
    sid = uuid.uuid4().hex
    _guardar(sid, Sessao())
    return sid


def obter_sessao(sid: str) -> Sessao:
    # ID fora do formato de nova_sessao() recebe uma sessão avulsa, que não ocupa memória.
    if not isinstance(sid, str) or not _RX_ID.fullmatch(sid):
        return Sessao()
    if sid in SESSOES:
        SESSOES.move_to_end(sid)
        return SESSOES[sid]
    return _guardar(sid, Sessao())
