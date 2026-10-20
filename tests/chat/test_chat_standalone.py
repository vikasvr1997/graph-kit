"""Regression tests for running chat when the graph implementation is absent."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from fastapi.testclient import TestClient


def test_chat_only_image_layout_works_without_graph_modules(tmp_path):
    source = Path(__file__).resolve().parents[2] / "graphkit"
    package = tmp_path / "graphkit"
    package.mkdir()
    shutil.copy(source / "__init__.py", package / "__init__.py")
    for name in ["chat", "shared", "api"]:
        shutil.copytree(source / name, package / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    code = '''
import json, sys
from fastapi.testclient import TestClient
from graphkit.api.application import app
from graphkit.chat.agent import build_agent
from graphkit.chat.eval import DEFAULT_CASES
client = TestClient(app)
agent = build_agent(graph_enabled=False)
assert not agent.tools
assert agent.before_model_callback and agent.after_model_callback
assert all(case['expect_tool'] is None for case in DEFAULT_CASES)
assert client.get('/api/capabilities').json() == {'graphkit': False, 'chat': True}
assert client.get('/api/chat/sessions').status_code == 401
for path in ['/api/graphs', '/api/scan', '/api/semantic/state', '/api/bench']:
    assert client.get(path).status_code == 404
assert client.get('/api/models').json()['embedding_models'] == []
assert not any(n.startswith(('graphkit.graph.core', 'graphkit.graph.agents', 'graphkit.graph.semantic',
                            'graphkit.graph.benchmarking', 'graphkit.graph.ui', 'graphkit.graph.adapters'))
               for n in sys.modules)
print(json.dumps({'ok': True}))
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "GRAPHKIT_ENABLED": "false", "CHAT_ENABLED": "true",
             "GOOGLE_CLOUD_PROJECT": "test-project"}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True}


def test_chat_only_message_skips_workspace_and_embeddings(monkeypatch):
    from graphkit.chat import api as chat
    from graphkit.api.application import create_app
    from graphkit.chat.auth import require_user

    monkeypatch.setenv("GRAPHKIT_ENABLED", "false")
    monkeypatch.setenv("CHAT_ENABLED", "true")
    app = create_app()
    app.dependency_overrides[require_user] = lambda: "user"
    messages = []

    class Store:
        @staticmethod
        def get_session(uid, sid):
            return {"generation_model": "test-model", "embedding_model": "unused"}

        @staticmethod
        def append_message(uid, sid, role, **fields):
            message = {"id": str(len(messages)), "role": role, **fields}
            messages.append(message)
            return message

    runner = object()

    def get_runner(**kwargs):
        assert kwargs == {"generation_model": "test-model", "graph_enabled": False}
        return runner

    async def run_turn(actual_runner, sid, text, attachments):
        assert actual_runner is runner
        yield "token", "Hello"
        yield "result", {"answer": "Hello", "status": "success"}

    monkeypatch.setattr(chat, "chat_store", Store)
    monkeypatch.setattr(chat, "get_runner", get_runner)
    monkeypatch.setattr(chat, "run_turn", run_turn)
    response = TestClient(app).post('/api/chat/sessions/s1/messages', json={"text": "Hi"})
    assert response.status_code == 200
    assert 'event: done' in response.text
    assert messages[-1]["text"] == "Hello"


def test_standalone_chat_keeps_content_guards(monkeypatch):
    from google.genai import types
    from graphkit.chat import agent
    from graphkit.chat import guardrails

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    assistant = agent.build_agent(graph_enabled=False)

    def block(text, project):
        raise guardrails.Blocked(["test content policy"])

    monkeypatch.setattr(guardrails, "check_prompt", block)
    request = type("Request", (), {"contents": [types.Content(parts=[types.Part(text="unsafe")])]})()
    refused = assistant.before_model_callback(None, request)
    assert "can't help" in refused.content.parts[0].text
    monkeypatch.setattr(guardrails, "check_response", block)
    reply = agent._refuse("unsafe output")
    refused = assistant.after_model_callback(None, reply)
    assert "withheld" in refused.content.parts[0].text


def test_graph_tools_are_optional_and_keep_query_guards(monkeypatch):
    from graphkit.chat.agent import build_agent
    from graphkit.graph.agents.dataset_guardrails import check_query
    import pytest

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    assistant = build_agent(object(), lambda _: {}, lambda _: [], "embedding", "model")
    assert {tool.__name__ for tool in assistant.tools} == {"query_dataset", "make_chart"}
    with pytest.raises(ValueError, match="read-only"):
        check_query("DELETE FROM suppliers", "sql")


def test_default_graph_server_does_not_load_chat():
    code = """
import sys
from fastapi.testclient import TestClient
from graphkit.api.application import app
client = TestClient(app)
assert client.get('/api/capabilities').json() == {'graphkit': True, 'chat': False}
assert client.get('/api/graphs').status_code == 200
assert client.get('/api/chat/sessions').status_code == 404
assert not any(n.startswith(('graphkit.chat', 'graphkit.chat.api', 'google.adk')) for n in sys.modules)
"""
    env = {**os.environ, "GRAPHKIT_ENABLED": "true"}
    env.pop("CHAT_ENABLED", None)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_chat_can_be_enabled_with_graph_server():
    code = """
from fastapi.testclient import TestClient
from graphkit.api.application import app
client = TestClient(app)
assert client.get('/api/capabilities').json() == {'graphkit': True, 'chat': True}
assert client.get('/api/chat/sessions').status_code == 401
assert client.get('/api/graphs').status_code == 200
"""
    result = subprocess.run([sys.executable, "-c", code],
        env={**os.environ, "GRAPHKIT_ENABLED": "true", "CHAT_ENABLED": "true"},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
