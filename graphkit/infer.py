"""Turn scanned tables into a proposed graph.

How a link between two tables is found, strongest evidence first:
  1. A declared foreign key (or Spanner interleaving).                 confidence 1.0
  2. A column description that says "references <table>".             0.8, raised by a value check
  3. A column whose name matches another table's key (supplier_id).   0.6, adjusted by a value check
  4. A text column whose sampled values all appear in another
     table's key column, even with an unrelated name.                 0.5

The value check takes the column's sampled values and asks the database
how many of them exist in the other table's key. That costs one small
query per candidate link.

Then each table becomes a node, or, if it only joins two other tables
(like part_usage(part_id, model_id)), an edge between them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .adapters.base import Adapter, TableInfo
from .model import NEW, Edge, GraphSpec, Node

NUMERIC = {"INT64", "NUMERIC"}


@dataclass
class Link:
    table: str
    cols: list[str]
    ref_table: str
    ref_cols: list[str]
    confidence: float
    reason: str


@dataclass
class InferResult:
    spec: GraphSpec
    notes: list[str] = field(default_factory=list)  # tables skipped and why, for the UI


# ---------- naming ----------
def singular(word: str) -> str:
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        return word[:-3] + "y"
    if w.endswith(("sses", "shes", "ches", "xes")):
        return word[:-2]
    if w.endswith("s") and not w.endswith("ss"):
        return word[:-1]
    return word


def node_label(table: str) -> str:
    parts = re.split(r"[_\W]+", table)
    parts[-1] = singular(parts[-1])
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def edge_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


# ---------- keys ----------
def _unique(sample: list[dict], cols: list[str]) -> bool:
    keys = [tuple(r.get(c) for c in cols) for r in sample]
    return all(None not in k for k in keys) and len(set(keys)) == len(keys)


def guess_key(t: TableInfo) -> list[str]:
    """Declared primary key, or the first id-like column that is unique in the sample."""
    if t.primary_key:
        return list(t.primary_key)
    names = [c.name for c in t.columns]
    candidates = ["id", f"{singular(t.name)}_id", f"{t.name}_id"]
    candidates += [n for n in names if n.lower().endswith(("_id", "_key", "_code"))]
    for c in candidates:
        if c in names and (not t.sample or _unique(t.sample, [c])):
            return [c]
    return []


def _types_ok(a: str, b: str) -> bool:
    if "OTHER" in (a, b):
        return False
    return a == b or (a in NUMERIC and b in NUMERIC)


def _values(t: TableInfo, col: str) -> list:
    return sorted({r[col] for r in t.sample if r.get(col) is not None}, key=str)[:200]


_REF = re.compile(r"(?:references?|foreign key (?:to|of|into)|points? to|links? to|id of (?:the|a|an)?)\s+`?([\w.]+)`?", re.I)


def _described_target(desc: str, names: set[str]) -> str | None:
    for m in _REF.finditer(desc or ""):
        parts = m.group(1).strip(".").split(".")
        for p in reversed(parts):
            for n in names:
                if p.lower() in (n.lower(), singular(n).lower()):
                    return n
    return None


# ---------- link discovery ----------
def find_links(tables: list[TableInfo], adapter: Adapter | None = None, check_values: bool = True) -> list[Link]:
    by_name = {t.name: t for t in tables}
    keys = {t.name: guess_key(t) for t in tables}
    links: dict[tuple, Link] = {}

    def add(link: Link):
        k = (link.table, tuple(link.cols), link.ref_table)
        if k not in links or links[k].confidence < link.confidence:
            links[k] = link

    def containment(t: TableInfo, col: str, u: str) -> float | None:
        vals = _values(t, col)
        if not vals or not check_values or adapter is None:
            return None
        return adapter.count_matches(u, keys[u][0], vals) / len(vals)

    for t in tables:
        declared = set()
        for fk in t.foreign_keys:
            if fk.ref_table in by_name:
                add(Link(t.name, fk.columns, fk.ref_table, fk.ref_columns, 1.0,
                         f"declared foreign key {', '.join(fk.columns)} -> {fk.ref_table}"))
                declared.update(fk.columns)

        for col in t.columns:
            if col.name in declared or keys[t.name] == [col.name]:
                continue
            for u in tables:
                ukey = keys[u.name]
                if len(ukey) != 1:
                    continue
                kcol = u.column(ukey[0])
                if kcol is None or not _types_ok(col.type, kcol.type):
                    continue
                if u.name == t.name and col.name == ukey[0]:
                    continue
                p, c = ukey[0].lower(), col.name.lower()
                stem = singular(u.name).lower()
                by_name_match = (c == p and p != "id") or c == f"{stem}_id" or c.endswith("_" + p) and p != "id" \
                    or (p == "id" and c.endswith(f"{stem}_id"))
                described = _described_target(col.description, {u.name}) == u.name
                if not (by_name_match or described):
                    continue
                share = containment(t, col.name, u.name)
                if share is not None and share < 0.5:
                    continue  # the name fits but the values don't
                base = 0.8 if described else 0.6
                reasons = []
                if described:
                    reasons.append(f"description of {col.name} mentions {u.name}")
                if by_name_match:
                    reasons.append(f"{col.name} matches {u.name}.{ukey[0]}")
                if share is not None:
                    base = (0.5 if described else 0.4) + 0.5 * share
                    reasons.append(f"{share:.0%} of sampled values found")
                add(Link(t.name, [col.name], u.name, ukey, round(min(base, 0.99), 2), "; ".join(reasons)))

        # Value-only matches: text columns whose sample sits entirely inside another
        # table's (fully sampled) key column. Checked locally, no queries.
        for col in t.columns:
            if col.type != "STRING" or col.name in declared or keys[t.name] == [col.name]:
                continue
            vals = set(map(str, _values(t, col.name)))
            if len(vals) < 3:
                continue
            for u in tables:
                if u.name == t.name or len(keys[u.name]) != 1 or (t.name, (col.name,), u.name) in links:
                    continue
                ukey = keys[u.name][0]
                if (u.column(ukey) or col).type != "STRING":
                    continue
                if vals <= {str(r.get(ukey)) for r in u.sample}:
                    add(Link(t.name, [col.name], u.name, [ukey], 0.5,
                             f"all {len(vals)} sampled values of {col.name} found in {u.name}.{ukey}"))
    # One link per (table, column set): keep the most confident target.
    best: dict[tuple, Link] = {}
    for link in links.values():
        k = (link.table, tuple(link.cols))
        if k not in best or best[k].confidence < link.confidence:
            best[k] = link
    return sorted(best.values(), key=lambda l: (l.table, l.cols))


# ---------- graph building ----------
def infer(tables: list[TableInfo], adapter: Adapter | None = None, *, name: str, backend: str,
          location: dict, min_confidence: float = 0.5, check_values: bool = True) -> InferResult:
    notes: list[str] = []
    keys = {t.name: guess_key(t) for t in tables}
    links = [l for l in find_links(tables, adapter, check_values) if l.confidence >= min_confidence]

    out_links: dict[str, list[Link]] = {}
    referenced = set()
    for l in links:
        out_links.setdefault(l.table, []).append(l)
        referenced.add(l.ref_table)

    def is_junction(t: TableInfo) -> bool:
        ls = out_links.get(t.name, [])
        return len(ls) == 2 and t.name not in referenced

    labels = {}
    nodes = []
    for t in tables:
        if is_junction(t):
            continue
        if not keys[t.name]:
            notes.append(f"Skipped {t.name}: no key column found. Add a primary key or pick one in the editor.")
            continue
        labels[t.name] = node_label(t.name)
        nodes.append(Node(label=labels[t.name], table=t.name, key=keys[t.name], description=t.description))

    used = set(labels.values())

    def unique(lbl: str) -> str:
        out, i = lbl, 2
        while out in used:
            out, i = f"{lbl}_{i}", i + 1
        used.add(out)
        return out

    edges = []
    for t in tables:
        ls = out_links.get(t.name, [])
        if is_junction(t):
            a, b = sorted(ls, key=lambda l: [c.name for c in t.columns].index(l.cols[0]))
            if a.ref_table not in labels or b.ref_table not in labels:
                notes.append(f"Skipped edge table {t.name}: it links to a table that isn't a node.")
                continue
            key = keys[t.name] if keys[t.name] and set(keys[t.name]) != set(a.cols) else a.cols + b.cols
            edges.append(Edge(
                label=unique(edge_label(t.name)), table=t.name, key=key,
                source=labels[a.ref_table], source_key=a.cols, dest=labels[b.ref_table], dest_key=b.cols,
                confidence=min(a.confidence, b.confidence),
                reason=f"{t.name} joins {a.ref_table} and {b.ref_table} ({a.reason}; {b.reason})",
            ))
            continue
        if t.name not in labels:
            continue
        for l in ls:
            if l.ref_table not in labels:
                continue
            if l.ref_cols != keys[l.ref_table]:
                notes.append(f"Skipped link {t.name}.{','.join(l.cols)}: it points at columns that aren't {l.ref_table}'s key.")
                continue
            base = re.sub(r"_(id|key|code)$", "", l.cols[0], flags=re.I) if len(l.cols) == 1 else singular(l.ref_table)
            edges.append(Edge(
                label=unique("HAS_" + edge_label(base)), table=t.name, key=keys[t.name],
                source=labels[t.name], source_key=keys[t.name], dest=labels[l.ref_table], dest_key=l.cols,
                confidence=l.confidence, reason=l.reason,
            ))

    for t in tables:
        if t.name in labels and not any(e.source == labels[t.name] or e.dest == labels[t.name] for e in edges):
            notes.append(f"{labels[t.name]} ({t.name}) has no links yet. Add an edge in the editor if it should.")
    spec = GraphSpec(name=name, backend=backend, location=location, nodes=nodes, edges=edges)
    return InferResult(spec=spec, notes=notes)


# ---------- updating an approved graph ----------
def _edge_id(e: Edge) -> tuple:
    return (e.table, tuple(e.source_key), tuple(e.dest_key))


def merge(approved: GraphSpec, found: GraphSpec, scanned: set[str] | None = None) -> tuple[GraphSpec, list[str]]:
    """Keep everything already approved; add what's new in `found`, marked NEW.

    Returns the merged spec and notes about tables that disappeared.
    """
    notes = []
    merged = GraphSpec.from_dict(approved.to_dict())
    have_tables = {n.table for n in merged.nodes}
    have_edges = {_edge_id(e) for e in merged.edges}
    rename = {}
    for n in found.nodes:
        if n.table in have_tables:
            rename[n.label] = next(m.label for m in merged.nodes if m.table == n.table)
            continue
        if n.label in {m.label for m in merged.nodes}:
            rename[n.label] = n.label = f"{n.label}_new"
        n.status = NEW
        merged.nodes.append(n)
    labels = {m.label for m in merged.nodes} | {e.label for e in merged.edges}
    for e in found.edges:
        e.source, e.dest = rename.get(e.source, e.source), rename.get(e.dest, e.dest)
        if _edge_id(e) in have_edges:
            continue
        while e.label in labels:
            e.label += "_NEW"
        labels.add(e.label)
        e.status = NEW
        merged.edges.append(e)
    found_tables = scanned if scanned is not None else found.tables()
    for n in approved.nodes:
        if n.table not in found_tables:
            notes.append(f"Table {n.table} (node {n.label}) wasn't found in the latest scan.")
    return merged, notes
