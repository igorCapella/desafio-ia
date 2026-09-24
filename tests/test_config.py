import os
from app.config import Settings


def test_defaults_sem_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek/deepseek-v4.1-flash"
    assert s.reasoning_effort == "high"
    assert s.orcamento_usd == 3.0
    assert s.mascarar_cpf is True


def test_le_do_ambiente(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-x")
    monkeypatch.setenv("REASONING_EFFORT", "max")
    monkeypatch.setenv("ORCAMENTO_USD", "1.5")
    s = Settings(_env_file=None)
    assert s.reasoning_effort == "max"
    assert s.orcamento_usd == 1.5
