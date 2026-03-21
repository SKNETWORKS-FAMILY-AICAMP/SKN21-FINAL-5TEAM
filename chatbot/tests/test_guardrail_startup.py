import sys
from pathlib import Path
import types

import logging

from langchain_core.messages import HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

langchain_ollama = types.ModuleType("langchain_ollama")


class _DummyChatOllama:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


langchain_ollama.ChatOllama = _DummyChatOllama
sys.modules.setdefault("langchain_ollama", langchain_ollama)

from chatbot.src.graph.nodes import guardrail
from ecommerce.backend.app import main as backend_main


def test_should_preload_heavy_models_once_per_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(backend_main, "_MODEL_PRELOAD_MARKER", tmp_path / "marker.flag", raising=False)

    assert backend_main._should_preload_heavy_models_once_per_reload_session() is True
    assert backend_main._should_preload_heavy_models_once_per_reload_session() is True


class _FakeConfig:
    id2label = {0: "safe", 1: "abuse", 2: "prompt_injection"}


class _FakeModel:
    config = _FakeConfig()


class _FakePipeline:
    def __init__(self, label: str = "SAFE", score: float = 0.95):
        self.model = _FakeModel()
        self._label = label
        self._score = score

    def __call__(self, _text):
        return [[{"label": self._label, "score": self._score}]]


def test_load_guardrail_model_logs_label_metadata(monkeypatch, caplog):
    monkeypatch.setattr(guardrail, "_GUARDRAIL_PIPELINE", None)
    monkeypatch.setattr(guardrail, "pipeline", lambda **_kwargs: _FakePipeline())

    with caplog.at_level(logging.INFO):
        guardrail.load_guardrail_model()

    assert guardrail.is_guardrail_loaded() is True
    assert "총 3개 클래스" in caplog.text
    assert "0=safe, 1=abuse, 2=prompt_injection" in caplog.text


def test_guardrail_node_allows_safe_label(monkeypatch):
    monkeypatch.setattr(guardrail, "_GUARDRAIL_PIPELINE", _FakePipeline(label="SAFE", score=0.12))

    result = guardrail.guardrail_node({"messages": [HumanMessage(content="안녕")]})

    assert result == {"guardrail_passed": True}


def test_guardrail_node_blocks_non_safe_label_even_with_low_confidence(monkeypatch):
    monkeypatch.setattr(guardrail, "_GUARDRAIL_PIPELINE", _FakePipeline(label="abuse", score=0.01))

    result = guardrail.guardrail_node({"messages": [HumanMessage(content="욕설 테스트")]})

    assert result["guardrail_passed"] is False
