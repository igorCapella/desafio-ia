import re
import uuid
from collections import OrderedDict

_RX_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_RX_CPF_TEXTO = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_MAX_CPFS = 20  # CPFs digitados aceitos por conversa (impede testar milhares de candidatos)


class Sessao:
    def __init__(self) -> None:
        self.historico: list[dict] = []
        self.processo_em_foco: str | None = None
        self.foco_resumo: dict = {}
        self.custo_total: float = 0.0
        # O que as ferramentas mostraram nesta conversa: base das verificações (spec §6)
        # e do acesso a documentos pela interface (spec §7).
        self.docs_vistos: dict[int, str] = {}
        self.movs_vistas: set[tuple[str, str]] = set()
        self.processos_consultados: set[str] = set()
        # CPFs (só dígitos) digitados pelo usuário: os únicos aceitos na busca por CPF.
        self.cpfs_do_usuario: set[str] = set()

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

    def compactar_dossies_antigos(self, ate: int | None = None) -> None:
        # Sem `ate`: compacta os dossiês que não são do processo em foco. Com `ate`: compacta
        # todos os anteriores a esse índice — o turno atual acabou de abrir um dossiê, que
        # substitui as cópias antigas (inclusive a do mesmo processo).
        for m in self.historico[:ate]:
            num = m.get("_numero")
            antigo = ate is not None or num != self.processo_em_foco
            if (m.get("role") == "tool" and m.get("name") == "obter_dossie" and num and antigo
                    and not m.get("_compactado")):
                m["content"] = f"[dossiê de {num} omitido; chame obter_dossie de novo se precisar]"
                m["_compactado"] = True

    def registrar_pergunta(self, pergunta: str) -> None:
        for m in _RX_CPF_TEXTO.findall(pergunta):
            if len(self.cpfs_do_usuario) >= _MAX_CPFS:
                break
            self.cpfs_do_usuario.add(re.sub(r"\D", "", m))

    def registrar_resultado(self, nome: str, res: dict) -> None:
        if nome == "obter_dossie" and res.get("encontrado"):
            self.processos_consultados.add(res["processo"]["numero"])
            for d in res["documentos"]:
                self.docs_vistos[d["id"]] = d["texto"] or ""
            for m in res["movimentacoes"]:
                self.movs_vistas.add((m["data"], m["descricao"]))
        elif nome == "buscar_processos":
            self.processos_consultados.update(p["numero"] for p in res.get("processos", []))
        elif nome == "consultar_sql":
            for linha in res.get("linhas", []):
                self.processos_consultados.update(
                    v for v in linha if isinstance(v, str) and _RX_CNJ.fullmatch(v))


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
