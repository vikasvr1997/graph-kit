"""The graph spec: which tables are nodes, which are edges, and how they link.

Everything else in the kit reads or writes this one structure. It is saved
as plain JSON so a developer can review it in a pull request.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Status of each node or edge as it moves through review.
PROPOSED = "proposed"  # found by a scan, not reviewed yet
APPROVED = "approved"  # confirmed by a developer and applied
NEW = "new"  # found by the watcher after the graph was approved


@dataclass
class Node:
    label: str  # e.g. "Supplier"
    table: str  # e.g. "suppliers"
    key: list[str]  # columns that identify one node
    properties: list[str] | None = None  # None = all columns
    description: str = ""
    status: str = PROPOSED


@dataclass
class Edge:
    label: str  # e.g. "SUPPLIES"
    table: str  # table that holds the link (a junction table, or the node table with the FK)
    key: list[str]  # columns that identify one edge
    source: str  # source node label
    source_key: list[str]  # columns in `table` that point at the source node
    dest: str  # destination node label
    dest_key: list[str]  # columns in `table` that point at the destination node
    bidirectional: bool = False  # also add a reverse edge so queries can go both ways
    reverse_label: str = ""  # label of that reverse edge, e.g. "SUPPLIED_BY"
    properties: list[str] | None = None
    confidence: float = 1.0  # how sure the scan was, 0 to 1
    reason: str = ""  # why the scan thinks this link exists
    status: str = PROPOSED

    def reverse_name(self) -> str:
        return self.reverse_label or f"{self.label}_REV"


@dataclass
class GraphSpec:
    name: str
    backend: str  # "bigquery", "spanner" or "sqlite"
    location: dict  # bigquery: project, dataset; spanner: project, instance, database; sqlite: path
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    # ---------- lookup ----------
    def node(self, label: str) -> Node:
        for n in self.nodes:
            if n.label == label:
                return n
        raise KeyError(f"No node labelled {label!r}")

    def tables(self) -> set[str]:
        return {n.table for n in self.nodes} | {e.table for e in self.edges}

    def directed_edges(self) -> list[tuple[str, Edge, bool]]:
        """Every edge as the graph sees it: (label, edge, reversed).

        A bidirectional edge shows up twice, once in each direction.
        """
        out = []
        for e in self.edges:
            out.append((e.label, e, False))
            if e.bidirectional:
                out.append((e.reverse_name(), e, True))
        return out

    # ---------- checks ----------
    def validate(self) -> list[str]:
        """Return a list of problems. Empty means the spec can be applied."""
        problems = []
        labels = [n.label for n in self.nodes] + [lbl for lbl, _, _ in self.directed_edges()]
        for lbl in {x for x in labels if labels.count(x) > 1}:
            problems.append(f"Label {lbl!r} is used more than once.")
        for lbl in labels:
            if not lbl or not lbl.replace("_", "").isalnum():
                problems.append(f"Label {lbl!r} must be letters, digits and _ only.")
        node_labels = {n.label for n in self.nodes}
        for n in self.nodes:
            if not n.key:
                problems.append(f"Node {n.label} needs at least one key column.")
        for e in self.edges:
            for end in (e.source, e.dest):
                if end not in node_labels:
                    problems.append(f"Edge {e.label} points at unknown node {end!r}.")
            if not e.key:
                problems.append(f"Edge {e.label} needs at least one key column.")
            if e.source in node_labels and len(e.source_key) != len(self.node(e.source).key):
                problems.append(f"Edge {e.label}: source_key must have as many columns as {e.source}'s key.")
            if e.dest in node_labels and len(e.dest_key) != len(self.node(e.dest).key):
                problems.append(f"Edge {e.label}: dest_key must have as many columns as {e.dest}'s key.")
        return problems

    # ---------- save / load ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GraphSpec":
        return cls(
            name=d["name"],
            backend=d["backend"],
            location=d.get("location", {}),
            nodes=[Node(**n) for n in d.get("nodes", [])],
            edges=[Edge(**e) for e in d.get("edges", [])],
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "GraphSpec":
        return cls.from_dict(json.loads(Path(path).read_text()))


def diff(old: GraphSpec | None, new: GraphSpec) -> dict[str, list[str]]:
    """What changes if `new` replaces `old`, by label."""
    def index(spec):
        if spec is None:
            return {}
        items = {f"node:{n.label}": asdict(n) for n in spec.nodes}
        items |= {f"edge:{e.label}": asdict(e) for e in spec.edges}
        for v in items.values():
            v.pop("status", None)
            v.pop("confidence", None)
            v.pop("reason", None)
        return items

    a, b = index(old), index(new)
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }
