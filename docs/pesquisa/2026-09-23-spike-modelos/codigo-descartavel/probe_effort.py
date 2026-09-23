"""SPIKE DESCARTÁVEL — quais níveis de reasoning effort o DeepSeek Flash aceita no OpenRouter."""
import socket, json, time, urllib.request, urllib.error
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: [r for r in _gai(*a, **k) if r[0] == socket.AF_INET]
env = dict(l.strip().split("=", 1) for l in open("/home/igor/dev/desafio-ia/.env") if "=" in l and not l.lstrip().startswith("#"))
PROMPT = "Considere os inteiros de 1 a 60. Quantos são divisíveis por 3 ou por 5, mas não por 15? Responda só com o número."
def call(model, reasoning):
    body = {"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 16000,
            "usage": {"include": True}, "provider": {"require_parameters": True}}
    if reasoning is not None: body["reasoning"] = reasoning
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {env['OPENROUTER_API_KEY']}", "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=240) as r: d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode()[:220]}"
    if d.get("error"): return f"ERRO: {json.dumps(d['error'])[:220]}"
    u = d.get("usage", {}); m = d["choices"][0]["message"]
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    return (f"resp={(m.get('content') or '').strip()[:12]!r:14} reasoning_tokens={rt!s:>6} out={u.get('completion_tokens'):>6} "
            f"{time.monotonic()-t0:5.1f}s US${u.get('cost', 0):.5f} provider={d.get('provider')}")
for model in ["deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-flash"]:
    print(f"\n### {model}")
    for label, r in [("padrão (sem parâmetro)", None), ("enabled=false", {"enabled": False}), ("effort=minimal", {"effort": "minimal"}),
                     ("effort=low", {"effort": "low"}), ("effort=medium", {"effort": "medium"}), ("effort=high", {"effort": "high"}),
                     ("effort=xhigh", {"effort": "xhigh"}), ("effort=max", {"effort": "max"})]:
        print(f"  {label:24} {call(model, r)}", flush=True)
