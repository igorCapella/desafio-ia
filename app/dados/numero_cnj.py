import re


def normalizar_numero(entrada: str) -> tuple[str | None, str | None]:
    d = re.sub(r"\D", "", entrada or "")
    if len(d) != 20:
        return None, "O número deve ter 20 dígitos no padrão CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO)."
    fmt = f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"
    esperado = 98 - int(d[:7] + d[9:] + "00") % 97
    if esperado != int(d[7:9]):
        return fmt, f"Dígito verificador inválido (o correto seria {esperado:02d}); confira o número."
    return fmt, None
