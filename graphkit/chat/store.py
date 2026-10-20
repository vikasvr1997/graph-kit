"""Firestore-backed chat session/message history, one store per user.

Uses the project's `(default)` Firestore Native database. The project also has a
database named `vertex-ai-chatbot`, which looked like an obvious fit by name, but
it was provisioned with `firestoreDataAccessMode: DISABLED` (Mongo-compatible API
only) - the standard Firestore client used here cannot reach it, and that setting
cannot be changed after creation. This is the only module that talks to Firestore
directly.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

DATABASE = "(default)"
_client = None


def client():
    global _client
    if _client is None:
        from google.cloud import firestore
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        _client = firestore.Client(project=project, database=DATABASE)
    return _client


def _now():
    return datetime.now(timezone.utc)


def _sessions(uid: str):
    return client().collection("users").document(uid).collection("sessions")


def create_session(uid: str, workspace: str, generation_model: str, embedding_model: str) -> dict:
    doc = _sessions(uid).document()
    data = {
        "id": doc.id, "title": "New chat", "workspace": workspace,
        "generation_model": generation_model, "embedding_model": embedding_model,
        "created_at": _now(), "updated_at": _now(),
    }
    doc.set(data)
    return data


def list_sessions(uid: str) -> list[dict]:
    docs = _sessions(uid).order_by("updated_at", direction="DESCENDING").stream()
    return [d.to_dict() for d in docs]


def get_session(uid: str, session_id: str) -> dict | None:
    doc = _sessions(uid).document(session_id).get()
    return doc.to_dict() if doc.exists else None


def rename_session(uid: str, session_id: str, title: str) -> None:
    _sessions(uid).document(session_id).update({"title": title, "updated_at": _now()})


def delete_session(uid: str, session_id: str) -> None:
    ref = _sessions(uid).document(session_id)
    for msg in ref.collection("messages").stream():
        msg.reference.delete()
    ref.delete()


def append_message(uid: str, session_id: str, role: str, **fields) -> dict:
    ref = _sessions(uid).document(session_id)
    msg_ref = ref.collection("messages").document()
    data = {"id": msg_ref.id, "role": role, "created_at": _now(), **fields}
    msg_ref.set(data)
    ref.update({"updated_at": _now()})
    return data


def list_messages(uid: str, session_id: str) -> list[dict]:
    docs = (_sessions(uid).document(session_id).collection("messages")
            .order_by("created_at").stream())
    return [d.to_dict() for d in docs]


def new_id() -> str:
    return uuid.uuid4().hex
