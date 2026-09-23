#!/usr/bin/env python3
"""SPIKE DESCARTÁVEL — mede, na minuta (B1), referências normativas que não estão nos autos."""
import json
import re
import sys
from pathlib import Path

SP = Path(__file__).resolve().parent
sys.path.insert(0, str(SP))
from spike_modelos import obter_dossie  # noqa: E402

autos = " ".join(d["texto"] for d in obter_dossie("0000001-81.2023.8.99.9011")["documentos"]).lower()
RX = re.compile(r"(s[úu]mula\s+(?:vinculante\s+)?n?[º°.]?\s*\d+(?:\s+do\s+\w+)?|art(?:igo|\.)\s*\d+[º°]?(?:,\s*(?:inciso\s+)?[ivxlc]+\b)?(?:,?\s*§\s*\d+[º°]?)?(?:,?\s*do\s+(?:c[óo]digo\s+\w+(?:\s+\w+)?|cpc|cc|cdc|lei\s+[\d\.\/]+)))", re.I)


def artigo_nos_autos(ref):
    n = re.search(r"\d+", ref).group(0)
    lei = "cpc" if re.search(r"cpc|processo civil", ref, re.I) else "civil" if re.search(r"\bcc\b|c[óo]digo civil", ref, re.I) else ""
    return bool(re.search(rf"art(?:igo|\.)\s*{n}\b", autos)) and (not lei or lei in autos)


for arq in sorted(SP.glob("spike_out/*.json")):
    if arq.stem.startswith("historico"):
        continue
    r = json.loads(arq.read_text())
    for c in r["casos"]:
        if c["caso"] != "B1":
            continue
        refs = sorted({m.group(0).strip() for m in RX.finditer(c["resposta"])})
        externas = [x for x in refs if (x.lower().startswith("s") and x.lower() not in autos) or (x.lower().startswith("art") and not artigo_nos_autos(x))]
        sumulas = [x for x in refs if x.lower().startswith("s")]
        print(f"{r['alias']:18} refs={len(refs):2} fora_dos_autos={len(externas):2} súmulas={sumulas}")
        for x in externas:
            print(f"      · {x}")
