"""Chat endpoints: session CRUD (Firestore) + a streaming (SSE) message endpoint
driving the ADK-based chat agent (graphkit/chatbot.py). Everything here requires
a signed-in user (`require_user`).
"""
from __future__ import annotations

import functools
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..chat import store as chat_store
from ..core import workflow
from ..agents.chat_agent import get_runner, run_turn
from ..agents.llm import MODEL as DEFAULT_GENERATION_MODEL
from ..semantic.workflow import GeminiEmbeddings
from .auth import require_user
from .model_catalog import DEFAULTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")


def ws(name: str) -> workflow.Workspace:
    root = Path(os.getenv("GRAPHKIT_HOME", "graphkit_out"))
    return workflow.Workspace(root, name)


# ---------------- sessions ----------------

class CreateSessionBody(BaseModel):
    workspace: str
    generation_model: str = DEFAULT_GENERATION_MODEL
    embedding_model: str = DEFAULTS["embedding_model"]


@router.post("/sessions")
def create_session(body: CreateSessionBody, uid: str = Depends(require_user)) -> dict:
    return chat_store.create_session(uid, body.workspace, body.generation_model, body.embedding_model)


@router.get("/sessions")
def list_sessions(uid: str = Depends(require_user)) -> list[dict]:
    return chat_store.list_sessions(uid)


class RenameBody(BaseModel):
    title: str


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameBody, uid: str = Depends(require_user)) -> dict:
    chat_store.rename_session(uid, session_id, body.title)
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, uid: str = Depends(require_user)) -> dict:
    chat_store.delete_session(uid, session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str, uid: str = Depends(require_user)) -> list[dict]:
    return chat_store.list_messages(uid, session_id)


# ---------------- messages (streamed) ----------------

class Attachment(BaseModel):
    mime_type: str
    data: str  # base64, used transiently for the model call - not persisted to Firestore


class SendMessageBody(BaseModel):
    text: str
    attachments: list[Attachment] = []
    generation_model: str | None = None
    embedding_model: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessageBody, uid: str = Depends(require_user)):
    session = chat_store.get_session(uid, session_id)
    if session is None:
        raise HTTPException(404, "Chat session not found. Start a new chat.")
    generation_model = body.generation_model or session["generation_model"]
    embedding_model = body.embedding_model or session["embedding_model"]
    attachment_meta = [{"mime_type": a.mime_type, "size": len(a.data)} for a in body.attachments]
    chat_store.append_message(uid, session_id, "user", text=body.text, attachments=attachment_meta)

    async def stream():
        from ..agents.llm import _ask
        ask = functools.partial(_ask, model=generation_model)
        try:
            embed_question = GeminiEmbeddings(embedding_model).question
        except Exception as e:  # noqa: BLE001 - e.g. missing Vertex AI credentials
            yield _sse("error", {"cause": str(e), "recovery": "Check Vertex AI access and retry."})
            return
        # The ADK runner/session-service is reused across turns of this session_id,
        # so the agent keeps real multi-turn tool-calling memory for the life of
        # this server process (see graphkit/chatbot.py's module docstring).
        runner = get_runner(ws(session["workspace"]), ask, embed_question, embedding_model, generation_model)
        attachments = [a.model_dump() for a in body.attachments]
        final: dict | None = None
        try:
            async for kind, payload in run_turn(runner, session_id, body.text, attachments):
                if kind == "status":
                    yield _sse("status", {"text": payload})
                elif kind == "token":
                    yield _sse("token", {"text": payload})
                elif kind == "chart":
                    yield _sse("chart", payload)
                elif kind == "result":
                    final = payload
        except Exception as e:  # noqa: BLE001 - surface cause + recovery, never a raw 500 mid-stream
            logger.exception("Chat turn failed")
            yield _sse("error", {"cause": str(e), "recovery": "Rephrase the question or try again."})
            final = {"status": "error", "answer": "", "error": str(e)}
        saved = chat_store.append_message(
            uid, session_id, "assistant", text=(final or {}).get("answer", ""),
            model=generation_model, query=(final or {}).get("query"),
            references=(final or {}).get("references", []),
            chart=(final or {}).get("chart"), rows=(final or {}).get("rows"),
        )
        yield _sse("done", saved)

    return StreamingResponse(stream(), media_type="text/event-stream")
