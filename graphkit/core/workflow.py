"""The kit's steps, shared by the CLI and the UI.

    scan -> (edit draft) -> confirm -> apply -> bench
                 ^                                 |
                 +-------- watch (new tables) <----+

Files for a graph live in <root>/<graph name>/:
    scan.json      tables, columns, descriptions and the sampled rows
    draft.json     the proposed graph; the UI edits this
    approved.json  the graph as last confirmed by a developer
    notes.json     what the scan skipped and why
    terraform/     generated Terraform and graph.sql
    bench.json     benchmark results; examples.json holds verified queries
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..benchmarking import runner as bench_mod
from ..benchmarking import generator as queries_mod
from ..adapters import Adapter, Column, ForeignKey, TableInfo, apply_descriptions, open_adapter, scan
from .infer import infer, merge
from .model import APPROVED, NEW, GraphSpec, diff
from .terraform import run_terraform, write_terraform


class Workspace:
    def __init__(self, root: str | Path, name: str):
        self.name = name
        self.dir = Path(root) / name
        self.dir.mkdir(parents=True, exist_ok=True)

    scan_path = property(lambda self: self.dir / "scan.json")
    draft_path = property(lambda self: self.dir / "draft.json")
    approved_path = property(lambda self: self.dir / "approved.json")
    notes_path = property(lambda self: self.dir / "notes.json")
    tf_dir = property(lambda self: self.dir / "terraform")

    def draft(self) -> GraphSpec | None:
        return GraphSpec.load(self.draft_path) if self.draft_path.exists() else None

    def approved(self) -> GraphSpec | None:
        return GraphSpec.load(self.approved_path) if self.approved_path.exists() else None

    def notes(self) -> list[str]:
        return json.loads(self.notes_path.read_text()) if self.notes_path.exists() else []

    def save_scan(self, tables: list[TableInfo]):
        self.scan_path.write_text(json.dumps([asdict(t) for t in tables], indent=1, default=str))

    def load_scan(self) -> list[TableInfo]:
        if not self.scan_path.exists():
            return []
        out = []
        for d in json.loads(self.scan_path.read_text()):
            d["columns"] = [Column(**c) for c in d["columns"]]
            d["foreign_keys"] = [ForeignKey(**f) for f in d["foreign_keys"]]
            out.append(TableInfo(**d))
        return out


def do_scan(ws: Workspace, backend: str, location: dict, *, sample_rows: int = 100,
            descriptions_file: str | None = None, check_values: bool = True,
            adapter: Adapter | None = None, use_llm: bool = False) -> tuple[GraphSpec, list[str]]:
    """Scan the source and save a draft. If a graph was already approved, keep it
    and add only what's new (marked "new") so nothing approved changes silently."""
    adapter = adapter or open_adapter(backend, location)
    tables = scan(adapter, sample_rows=sample_rows)
    apply_descriptions(tables, descriptions_file)
    ws.save_scan(tables)
    result = infer(tables, adapter, name=ws.name, backend=backend, location=location, check_values=check_values)
    spec, notes = result.spec, result.notes
    if use_llm:
        from ..agents.llm import refine
        spec, changes = refine(spec, tables)
        notes += [f"Gemini: {c}" for c in changes]
    approved = ws.approved()
    if approved:
        spec, gone = merge(approved, spec, scanned={t.name for t in tables})
        notes += gone
    spec.save(ws.draft_path)
    ws.notes_path.write_text(json.dumps(notes, indent=1))
    return spec, notes


def pending_changes(ws: Workspace) -> dict[str, list[str]]:
    draft = ws.draft()
    return diff(ws.approved(), draft) if draft else {"added": [], "removed": [], "changed": []}


def confirm(ws: Workspace, spec: GraphSpec) -> Path:
    """A developer approved `spec`: save it and write the Terraform. Does not apply."""
    problems = spec.validate()
    if problems:
        raise ValueError("\n".join(problems))
    approved = GraphSpec.from_dict(spec.to_dict())
    for item in approved.nodes + approved.edges:
        item.status = APPROVED
    approved.save(ws.approved_path)
    approved.save(ws.draft_path)
    if approved.backend in ("bigquery", "spanner"):
        return write_terraform(approved, ws.tf_dir)
    return ws.approved_path


def apply(ws: Workspace, action: str = "plan") -> tuple[int, str]:
    return run_terraform(ws.tf_dir, action)


def do_bench(ws: Workspace, adapter: Adapter | None = None, *, max_hops: int = 3, limit: int = 20,
             llm_questions: int = 0, repeat: int = 3):
    spec = ws.approved() or ws.draft()
    if spec is None:
        raise ValueError("Scan and confirm a graph first.")
    adapter = adapter or open_adapter(spec.backend, spec.location)
    qs = queries_mod.generate(spec, adapter, max_hops=max_hops, limit=limit)
    if llm_questions:
        from ..agents.llm import eval_queries
        qs += eval_queries(spec, ws.load_scan(), adapter, n=llm_questions)
    results = bench_mod.run_bench(adapter, qs, repeat=repeat)
    bench_mod.save(results, qs, ws.dir)
    return qs, results


def do_watch(ws: Workspace, adapter: Adapter | None = None, **scan_kwargs) -> list[str]:
    """Re-scan an approved graph's source. Returns labels of new items waiting for review."""
    approved = ws.approved()
    if approved is None:
        raise ValueError("Nothing approved yet. Run scan and confirm first.")
    spec, _ = do_scan(ws, approved.backend, approved.location, adapter=adapter, **scan_kwargs)
    return [n.label for n in spec.nodes if n.status == NEW] + [e.label for e in spec.edges if e.status == NEW]
