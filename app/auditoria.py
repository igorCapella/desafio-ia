import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.dados.conexao import py_mascarar_cpf

_RX_CPF = re.compile(r"(?<!\d)\d{3}[.\s]?\d{3}[.\s]?\d{3}[-\s]?\d{2}(?!\d)")
_RX_CHAVE = re.compile(r"(?i:bearer)\s+\S+|sk-or-v1-[0-9A-Za-z]+|sk-[0-9A-Za-z_-]{20,}|"
                       r"AIza[0-9A-Za-z_-]{30,}|AQ\.[0-9A-Za-z_-]{20,}")
_NOME_SEGREDO = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|SENHA", re.I)
_REMOVIDA = "[chave removida]"


def _segredos() -> list[str]:
    # Valores reais configurados: saem do log onde quer que apareçam, com qualquer formato.
    valores = {get_settings().openrouter_api_key}
    valores |= {v for k, v in os.environ.items() if _NOME_SEGREDO.search(k)}
    return sorted((v for v in valores if v and len(v) >= 8), key=len, reverse=True)


def _limpar_texto(v: str, segredos: list[str]) -> str:
    for segredo in segredos:
        v = v.replace(segredo, _REMOVIDA)
    v = _RX_CHAVE.sub(_REMOVIDA, v)
    return _RX_CPF.sub(lambda m: py_mascarar_cpf(m.group()), v)


def _limpar(v, segredos: list[str]):
    # CPF sempre mascarado e nenhuma chave no log (spec §9.3): em todo texto, inclusive chaves de dict;
    # qualquer objeto que não seja JSON nativo vira texto já limpo.
    if isinstance(v, str):
        return _limpar_texto(v, segredos)
    if isinstance(v, dict):
        return {_limpar(k, segredos) if isinstance(k, str) else k: _limpar(x, segredos)
                for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return [_limpar(x, segredos) for x in v]
    if v is None or isinstance(v, (bool, int, float)):
        return v
    return _limpar_texto(str(v), segredos)


def registrar(evento: dict, caminho: str = "logs/auditoria.jsonl") -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    linha = {"ts": datetime.now(timezone.utc).isoformat(), **_limpar(evento, _segredos())}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def custo_acumulado(caminho: str = "logs/auditoria.jsonl") -> float:
    p = Path(caminho)
    if not p.exists():
        return 0.0
    total = 0.0
    for linha in p.read_text(encoding="utf-8").splitlines():
        try:
            total += float(json.loads(linha).get("custo") or 0.0)
        except (ValueError, AttributeError, TypeError):
            continue  # linha corrompida (gravação interrompida) não derruba o teto de orçamento
    return total
