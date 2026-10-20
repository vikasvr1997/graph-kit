import os

import pytest
from fastapi.testclient import TestClient

from graphkit.core import workflow


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHKIT_HOME", str(tmp_path))
    from graphkit.api import server
    server.ROOT = tmp_path
    c = TestClient(server.app)
    c.graphkit_root = tmp_path
    return c


def test_scan_draft_edit_confirm_ddl(client, demo_db):
    r = client.post("/api/scan", json={
        "name": "SupplyChain", "backend": "sqlite", "location": {"path": str(demo_db)},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] > 0
    assert body["edges"] > 0

    r = client.get("/api/state", params={"name": "SupplyChain"})
    assert r.status_code == 200
    state = r.json()
    assert state["has_draft"] is True
    assert state["problems"] == []

    r = client.get("/api/draft", params={"name": "SupplyChain"})
    draft = r.json()
    assert draft["nodes"]
    assert draft["edges"]
    assert "part_usage" not in draft["label_opts"]  # label_opts are node labels, not tables

    # edit: drop a node's key to introduce a validation problem, save anyway
    bad_nodes = [dict(n) for n in draft["nodes"]]
    bad_nodes[0]["key"] = []
    r = client.put("/api/draft", json={"name": "SupplyChain", "nodes": bad_nodes, "edges": draft["edges"]})
    assert r.status_code == 200
    assert r.json()["problems"]  # the missing key is reported, not silently dropped

    r = client.get("/api/ddl", params={"name": "SupplyChain"})
    assert r.json()["ddl"] is None  # can't build DDL while there's a validation problem

    # restore a valid draft and confirm
    r = client.put("/api/draft", json={"name": "SupplyChain", "nodes": draft["nodes"], "edges": draft["edges"]})
    assert r.json()["problems"] == []

    r = client.get("/api/ddl", params={"name": "SupplyChain"})
    assert r.status_code == 200
    assert "CREATE OR REPLACE PROPERTY GRAPH" in r.json()["ddl"]

    r = client.post("/api/confirm", json={"name": "SupplyChain"})
    assert r.status_code == 200
    ws = workflow.Workspace(client.graphkit_root, "SupplyChain")
    assert ws.approved_path.exists()


def test_state_before_scan_returns_no_draft(client):
    r = client.get("/api/state", params={"name": "Nope"})
    assert r.status_code == 200
    assert r.json()["has_draft"] is False


def test_draft_missing_returns_404(client):
    r = client.get("/api/draft", params={"name": "Nope"})
    assert r.status_code == 404


def test_models_catalog_lists_validated_defaults(client):
    r = client.get("/api/models")
    assert r.status_code == 200
    body = r.json()
    assert body["defaults"]["embedding_model"] == "gemini-embedding-001"
    assert body["defaults"]["generation_model"] == "gemini-3.5-flash"
    assert any(m["id"] == body["defaults"]["embedding_model"] and m["validated"] for m in body["embedding_models"])
    assert any(m["id"] == body["defaults"]["generation_model"] and m["validated"] for m in body["generation_models"])


def test_semantic_propose_edit_approve(client, demo_db):
    client.post("/api/scan", json={"name": "SupplyChain", "backend": "sqlite", "location": {"path": str(demo_db)}})
    client.post("/api/confirm", json={"name": "SupplyChain"})

    r = client.post("/api/semantic/propose", json={"name": "SupplyChain", "use_llm": False})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items

    r = client.get("/api/semantic/catalog", params={"name": "SupplyChain", "which": "draft"})
    assert r.status_code == 200
    assert r.json()["approved"] is False

    items[0]["description"] = "edited by a developer"
    r = client.put("/api/semantic/draft", json={"name": "SupplyChain", "items": items})
    assert r.status_code == 200

    r = client.post("/api/semantic/approve", json={"name": "SupplyChain"})
    assert r.status_code == 200
    assert r.json()["approved"] is True

    r = client.get("/api/semantic/state", params={"name": "SupplyChain"})
    state = r.json()
    assert state["has_approved"] is True
    assert state["embeddings"] is None

    r = client.get("/api/terraform", params={"name": "SupplyChain"})
    assert "semantic.sql" in r.json()["files"]


def test_semantic_approve_without_draft_fails(client, demo_db):
    client.post("/api/scan", json={"name": "SupplyChain", "backend": "sqlite", "location": {"path": str(demo_db)}})
    client.post("/api/confirm", json={"name": "SupplyChain"})
    r = client.post("/api/semantic/approve", json={"name": "SupplyChain"})
    assert r.status_code == 400
