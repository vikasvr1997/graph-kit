"""FastAPI backend for the React UI.

    graphkit web                 # or: uvicorn graphkit.api.server:app --port 8765

Every endpoint is a thin wrapper around `graphkit.workflow` / `graphkit.model` /
`graphkit.ui.graph_view` / `graphkit.ddl` / `graphkit.terraform` - no logic lives here.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..core import workflow
from ..semantic import workflow as semantic_workflow
from ..adapters import open_adapter
from ..core.ddl import create_graph_ddl
from ..core.model import APPROVED, GraphSpec, Node, Edge
from ..semantic.catalog import Catalog, SemanticItem
from ..core.terraform import terraform_available
from ..ui.graph_view import colors as graph_colors, data_view, schema_view
from .chat import router as chat_router
from .model_catalog import DEFAULTS, EMBEDDING_MODELS, GENERATION_MODELS, NOTE

ROOT = Path(os.getenv("GRAPHKIT_HOME", "graphkit_out"))

app = FastAPI(title="graphkit")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(chat_router)


def ws(name: str) -> workflow.Workspace:
    return workflow.Workspace(ROOT, name)


def draft_or_404(w: workflow.Workspace) -> GraphSpec:
    spec = w.draft()
    if spec is None:
        raise HTTPException(404, f"No scan yet for {w.name!r}. Scan a source first.")
    return spec


def run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001 - surface any source/validation error to the UI
        raise HTTPException(400, str(e)) from e


# ---------------- workspaces / demo ----------------

@app.get("/api/graphs")
def list_graphs() -> list[str]:
    if not ROOT.exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir())


class DemoBody(BaseModel):
    path: str = "demo/supply_chain.db"


@app.post("/api/demo")
def create_demo(body: DemoBody) -> dict:
    from ..core.demo import make
    def _make():
        make(Path(body.path).parent)
        return {"path": body.path}
    return run(_make)


# ---------------- scan / watch / state ----------------

class ScanBody(BaseModel):
    name: str
    backend: str
    location: dict[str, Any]
    sample_rows: int = 100
    descriptions_file: str | None = None
    check_values: bool = True
    use_llm: bool = False


@app.post("/api/scan")
def scan(body: ScanBody) -> dict:
    spec, notes = run(workflow.do_scan, ws(body.name), body.backend, body.location,
                       sample_rows=body.sample_rows, descriptions_file=body.descriptions_file,
                       check_values=body.check_values, use_llm=body.use_llm)
    return {"nodes": len(spec.nodes), "edges": len(spec.edges), "notes": notes}


class WatchBody(BaseModel):
    name: str
    sample_rows: int = 100
    check_values: bool = True


@app.post("/api/watch")
def watch(body: WatchBody) -> dict:
    new = run(workflow.do_watch, ws(body.name), sample_rows=body.sample_rows, check_values=body.check_values)
    return {"new": new}


@app.get("/api/state")
def state(name: str) -> dict:
    w = ws(name)
    spec = w.draft()
    if spec is None:
        return {"has_draft": False, "has_approved": w.approved() is not None, "notes": w.notes()}
    problems = spec.validate()
    waiting = [x.label for x in spec.nodes + spec.edges if x.status != APPROVED]
    return {
        "has_draft": True,
        "has_approved": w.approved() is not None,
        "nodes": len(spec.nodes),
        "edges": len(spec.directed_edges()),
        "waiting": len(waiting),
        "problems": problems,
        "notes": w.notes(),
        "backend": spec.backend,
        "location": spec.location,
    }


# ---------------- draft editing ----------------

@app.get("/api/draft")
def get_draft(name: str) -> dict:
    w = ws(name)
    spec = draft_or_404(w)
    tables = w.load_scan()
    table_names = sorted({t.name for t in tables} | spec.tables())
    label_opts = sorted({n.label for n in spec.nodes})
    return {
        "nodes": [asdict(n) for n in spec.nodes],
        "edges": [asdict(e) for e in spec.edges],
        "table_names": table_names,
        "label_opts": label_opts,
        "backend": spec.backend,
        "location": spec.location,
    }


class DraftBody(BaseModel):
    name: str
    nodes: list[dict]
    edges: list[dict]


@app.put("/api/draft")
def put_draft(body: DraftBody) -> dict:
    w = ws(body.name)
    spec = draft_or_404(w)
    edited = GraphSpec(
        name=spec.name, backend=spec.backend, location=spec.location,
        nodes=[Node(**n) for n in body.nodes],
        edges=[Edge(**e) for e in body.edges],
    )
    problems = edited.validate()
    edited.save(w.draft_path)  # keep the edit even if it still has problems, like the Streamlit editor
    return {"problems": problems}


# ---------------- graph view ----------------

@app.get("/api/graph")
def graph(name: str, view: str = "schema", per: int = 8) -> dict:
    w = ws(name)
    spec = draft_or_404(w)
    if view == "data":
        nodes, edges = data_view(spec, w.load_scan(), per)
    else:
        nodes, edges = schema_view(spec)
    return {"nodes": nodes, "edges": edges, "colors": graph_colors(spec)}


# ---------------- review / confirm / ddl ----------------

@app.get("/api/changes")
def changes(name: str) -> dict:
    return run(workflow.pending_changes, ws(name))


@app.get("/api/ddl")
def ddl(name: str) -> dict:
    spec = draft_or_404(ws(name))
    problems = spec.validate()
    if problems:
        return {"ddl": None, "problems": problems, "preview": spec.backend == "sqlite"}
    preview = spec
    if spec.backend == "sqlite":
        preview = GraphSpec.from_dict({**spec.to_dict(), "backend": "bigquery",
                                       "location": {"project": "YOUR_PROJECT", "dataset": "YOUR_DATASET"}})
    return {"ddl": run(create_graph_ddl, preview), "problems": [], "preview": spec.backend == "sqlite"}


class ConfirmBody(BaseModel):
    name: str


@app.post("/api/confirm")
def confirm(body: ConfirmBody) -> dict:
    w = ws(body.name)
    spec = draft_or_404(w)
    out = run(workflow.confirm, w, spec)
    return {"path": str(out)}


@app.get("/api/terraform")
def terraform_files(name: str) -> dict:
    w = ws(name)
    if not w.tf_dir.exists():
        return {"available": False}
    files = {}
    for f in ("main.tf", "graph.sql", "semantic.tf", "semantic.sql"):
        p = w.tf_dir / f
        if p.exists():
            files[f] = p.read_text()
    return {"available": True, "files": files, "terraform_installed": terraform_available()}


@app.post("/api/terraform/plan")
def terraform_plan(body: ConfirmBody) -> dict:
    code, log = run(workflow.apply, ws(body.name), "plan")
    return {"code": code, "log": log}


@app.post("/api/terraform/apply")
def terraform_apply(body: ConfirmBody) -> dict:
    code, log = run(workflow.apply, ws(body.name), "apply")
    return {"code": code, "log": log}


# ---------------- benchmark ----------------

class BenchBody(BaseModel):
    name: str
    hops: int = 3
    limit: int = 20
    llm_n: int = 0
    repeat: int = 3


@app.post("/api/bench")
def bench(body: BenchBody) -> dict:
    w = ws(body.name)
    spec = w.approved() or draft_or_404(w)

    def _run():
        adapter = open_adapter(spec.backend, spec.location)
        return workflow.do_bench(w, adapter, max_hops=body.hops, limit=body.limit,
                                  llm_questions=body.llm_n, repeat=body.repeat)
    run(_run)
    return get_bench(body.name)


@app.get("/api/bench")
def get_bench(name: str) -> dict:
    bench_file = ws(name).dir / "bench.json"
    if not bench_file.exists():
        return {"available": False}
    return {"available": True, **json.loads(bench_file.read_text())}


# ---------------- model catalog (for the Semantic tab's dropdowns) ----------------

@app.get("/api/models")
def models() -> dict:
    return {"embedding_models": EMBEDDING_MODELS, "generation_models": GENERATION_MODELS,
            "defaults": DEFAULTS, "note": NOTE}


# ---------------- semantic catalog / embeddings / ask ----------------

def _catalog_response(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    c = Catalog.load(path)
    return {"exists": True, "revision": c.revision, "approved": c.approved,
            "items": [asdict(i) for i in c.items]}


@app.get("/api/semantic/state")
def semantic_state(name: str) -> dict:
    w = ws(name)
    emb_path = w.dir / "embeddings.json"
    embeddings = None
    if emb_path.exists():
        data = json.loads(emb_path.read_text())
        embeddings = {"model": data.get("model"), "count": len(data.get("ids", [])),
                      "dimensions": len(data["vectors"][0]) if data.get("vectors") else 0}
    return {
        "has_draft": (w.dir / "semantic.draft.json").exists(),
        "has_approved": (w.dir / "semantic.approved.json").exists(),
        "embeddings": embeddings,
    }


@app.get("/api/semantic/catalog")
def semantic_catalog(name: str, which: str = "draft") -> dict:
    if which not in ("draft", "approved"):
        raise HTTPException(400, "which must be 'draft' or 'approved'")
    return _catalog_response(ws(name).dir / f"semantic.{which}.json")


class SemanticProposeBody(BaseModel):
    name: str
    use_llm: bool = False
    model: str | None = None


@app.post("/api/semantic/propose")
def semantic_propose(body: SemanticProposeBody) -> dict:
    ask = None
    if body.use_llm:
        import functools
        from ..agents.llm import MODEL, _ask
        ask = functools.partial(_ask, model=body.model or MODEL)
    catalog = run(semantic_workflow.propose_catalog, ws(body.name), ask)
    return {"revision": catalog.revision, "items": [asdict(i) for i in catalog.items]}


class SemanticDraftBody(BaseModel):
    name: str
    items: list[dict]


@app.put("/api/semantic/draft")
def put_semantic_draft(body: SemanticDraftBody) -> dict:
    path = ws(body.name).dir / "semantic.draft.json"
    if not path.exists():
        raise HTTPException(404, "No semantic draft yet. Propose one first.")
    catalog = Catalog.load(path)
    catalog.items = [SemanticItem(**i) for i in body.items]
    catalog.approved = False
    catalog.save(path)
    return {"ok": True}


@app.post("/api/semantic/approve")
def semantic_approve(body: ConfirmBody) -> dict:
    catalog = run(semantic_workflow.approve_catalog, ws(body.name))
    return {"revision": catalog.revision, "approved": catalog.approved, "items": len(catalog.items)}


class SemanticEmbedBody(BaseModel):
    name: str
    embedding_model: str


@app.post("/api/semantic/embed")
def semantic_embed(body: SemanticEmbedBody) -> dict:
    def _run():
        embedder = semantic_workflow.GeminiEmbeddings(body.embedding_model)
        return semantic_workflow.embed_catalog(ws(body.name), embedder.documents, body.embedding_model)
    artifact = run(_run)
    return {"model": artifact["model"], "count": len(artifact["ids"]),
            "dimensions": len(artifact["vectors"][0]) if artifact["vectors"] else 0}


@app.post("/api/semantic/publish")
def semantic_publish(body: ConfirmBody) -> dict:
    return {"rows": run(semantic_workflow.publish, ws(body.name))}


class SemanticAskBody(BaseModel):
    name: str
    question: str
    embedding_model: str
    generation_model: str
    mode: str = "auto"


@app.post("/api/semantic/ask")
def semantic_ask(body: SemanticAskBody) -> dict:
    def _run():
        import functools
        from ..agents.dataset_agent import DatasetAgent
        from ..agents.llm import _ask
        embedder = semantic_workflow.GeminiEmbeddings(body.embedding_model)
        ask_fn = functools.partial(_ask, model=body.generation_model)
        agent = DatasetAgent(ws(body.name), ask_fn, embedder.question, body.embedding_model)
        return agent.answer(body.question, mode=body.mode)
    return run(_run)
