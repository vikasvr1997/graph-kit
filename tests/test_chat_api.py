import pytest
from fastapi.testclient import TestClient

from graphkit.api import chat as chat_module
from graphkit.api import server
from graphkit.api.auth import require_user


class FakeStore:
    """In-memory stand-in for graphkit.chat_store, keyed like the real Firestore schema."""

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}

    def create_session(self, uid, workspace, generation_model, embedding_model):
        session = {"id": f"s{len(self.sessions)}", "title": "New chat", "workspace": workspace,
                   "generation_model": generation_model, "embedding_model": embedding_model}
        self.sessions[session["id"]] = session
        self.messages[session["id"]] = []
        return session

    def list_sessions(self, uid):
        return list(self.sessions.values())

    def get_session(self, uid, session_id):
        return self.sessions.get(session_id)

    def rename_session(self, uid, session_id, title):
        self.sessions[session_id]["title"] = title

    def delete_session(self, uid, session_id):
        self.sessions.pop(session_id, None)
        self.messages.pop(session_id, None)

    def append_message(self, uid, session_id, role, **fields):
        msg = {"id": f"m{len(self.messages[session_id])}", "role": role, **fields}
        self.messages[session_id].append(msg)
        return msg

    def list_messages(self, uid, session_id):
        return list(self.messages[session_id])


async def fake_run_turn_ok(runner, session_id, message, attachments):
    yield "status", "Thinking..."
    yield "token", "Hello"
    yield "token", " world"
    yield "result", {"status": "success", "answer": "Hello world", "references": []}


async def fake_run_turn_fails(runner, session_id, message, attachments):
    yield "status", "Looking at the approved dataset..."
    raise ValueError("Approve the graph first.")


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(chat_module, "chat_store", fake)
    return fake


@pytest.fixture
def client(store):
    server.app.dependency_overrides[require_user] = lambda: "test-uid"
    yield TestClient(server.app)
    server.app.dependency_overrides.pop(require_user, None)


def _sse_events(response):
    events = []
    event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event = line.removeprefix("event: ")
        elif line.startswith("data: ") and event:
            events.append((event, line.removeprefix("data: ")))
    return events


def test_sessions_require_auth():
    client = TestClient(server.app)
    r = client.get("/api/chat/sessions")
    assert r.status_code == 401


def test_session_crud(client, store):
    r = client.post("/api/chat/sessions", json={"workspace": "SupplyChain"})
    assert r.status_code == 200
    session_id = r.json()["id"]

    r = client.get("/api/chat/sessions")
    assert len(r.json()) == 1

    r = client.patch(f"/api/chat/sessions/{session_id}", json={"title": "Renamed"})
    assert r.status_code == 200
    assert store.sessions[session_id]["title"] == "Renamed"

    r = client.delete(f"/api/chat/sessions/{session_id}")
    assert r.status_code == 200
    assert session_id not in store.sessions


def test_send_message_streams_tokens_and_persists(client, store, monkeypatch):
    monkeypatch.setattr(chat_module, "get_runner", lambda *a, **kw: object())
    monkeypatch.setattr(chat_module, "run_turn", fake_run_turn_ok)
    monkeypatch.setattr(chat_module, "GeminiEmbeddings", lambda model: type("E", (), {"question": None})())

    session = client.post("/api/chat/sessions", json={"workspace": "SupplyChain"}).json()
    r = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"text": "hi"})
    assert r.status_code == 200

    events = _sse_events(r)
    kinds = [e for e, _ in events]
    assert kinds[0] == "status"
    assert "token" in kinds
    assert kinds[-1] == "done"

    persisted = store.messages[session["id"]]
    assert persisted[0]["role"] == "user" and persisted[0]["text"] == "hi"
    assert persisted[1]["role"] == "assistant" and persisted[1]["text"] == "Hello world"


def test_send_message_to_missing_session_404(client):
    r = client.post("/api/chat/sessions/nope/messages", json={"text": "hi"})
    assert r.status_code == 404


def test_send_message_reports_agent_error_as_sse_event(client, store, monkeypatch):
    monkeypatch.setattr(chat_module, "get_runner", lambda *a, **kw: object())
    monkeypatch.setattr(chat_module, "run_turn", fake_run_turn_fails)
    monkeypatch.setattr(chat_module, "GeminiEmbeddings", lambda model: type("E", (), {"question": None})())

    session = client.post("/api/chat/sessions", json={"workspace": "SupplyChain"}).json()
    r = client.post(f"/api/chat/sessions/{session['id']}/messages", json={"text": "how many parts?"})
    assert r.status_code == 200

    events = _sse_events(r)
    assert events[-2][0] == "error"
    assert "Approve the graph first" in events[-2][1]
    assert events[-1][0] == "done"
