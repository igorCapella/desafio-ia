import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.dados.conexao import py_mascarar_cpf

_RX_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_RX_CHAVE = re.compile(r"sk-or-v1-[0-9A-Za-z]+|sk-[0-9A-Za-z_-]{20,}")


def _limpar(v):
    # CPF sempre mascarado e nenhuma chave de API no log (spec §9.3), em qualquer campo de texto.
    if isinstance(v, str):
        v = _RX_CPF.sub(lambda m: py_mascarar_cpf(m.group()), v)
        return _RX_CHAVE.sub("[chave removida]", v)
    if isinstance(v, dict):
        return {k: _limpar(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_limpar(x) for x in v]
    return v


def registrar(evento: dict, caminho: str = "logs/auditoria.jsonl") -> None:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    linha = {"ts": datetime.now(timezone.utc).isoformat(), **_limpar(evento)}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")


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
