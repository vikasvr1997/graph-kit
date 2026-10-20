"""Generate test queries from a graph: each one as GQL and as the equivalent SQL.

Running both and comparing the answers checks that the graph is wired
correctly (a wrong key gives a different count), and timing them shows
which form answers faster.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..adapters.base import Adapter
from ..core.model import Edge, GraphSpec


@dataclass
class EvalQuery:
    id: str
    question: str
    gql: str
    sql: str
    compare: str = "rows"  # "rows": compare all rows; "count": compare the single number
    source: str = "generated"  # "generated" or "llm"

    def to_dict(self):
        return asdict(self)


Step = tuple[str, Edge, bool, str]  # (edge label, edge, reversed, next node label)


def paths(spec: GraphSpec, max_hops: int = 3) -> list[tuple[str, list[Step]]]:
    """Every path up to max_hops long that never uses the same underlying edge twice."""
    adj: dict[str, list[Step]] = {n.label: [] for n in spec.nodes}
    for label, e, rev in spec.directed_edges():
        start, end = (e.dest, e.source) if rev else (e.source, e.dest)
        adj[start].append((label, e, rev, end))

    out = []

    def walk(start, steps):
        if steps:
            out.append((start, list(steps)))
        if len(steps) == max_hops:
            return
        here = steps[-1][3] if steps else start
        used = {(s[1].table, tuple(s[1].source_key), tuple(s[1].dest_key)) for s in steps}
        for step in adj[here]:
            if (step[1].table, tuple(step[1].source_key), tuple(step[1].dest_key)) not in used:
                walk(start, steps + [step])

    for n in spec.nodes:
        walk(n.label, [])
    out.sort(key=lambda p: (len(p[1]), p[0], [s[0] for s in p[1]]))
    return out


def _pattern(start: str, steps: list[Step]) -> str:
    s = f"(n0:{start})"
    for i, (label, _, _, end) in enumerate(steps, 1):
        s += f"-[:{label}]->(n{i}:{end})"
    return s


def _sql_joins(spec: GraphSpec, adapter: Adapter, start: str, steps: list[Step]) -> str:
    node = spec.node(start)
    sql = f"FROM {adapter.qualify(node.table)} AS n0"
    prev_key = node.key
    for i, (_, e, rev, end) in enumerate(steps, 1):
        src_cols, dst_cols = (e.dest_key, e.source_key) if rev else (e.source_key, e.dest_key)
        on = " AND ".join(f"e{i}.{a} = n{i-1}.{b}" for a, b in zip(src_cols, prev_key))
        sql += f"\nJOIN {adapter.qualify(e.table)} AS e{i} ON {on}"
        nxt = spec.node(end)
        on = " AND ".join(f"n{i}.{b} = e{i}.{a}" for a, b in zip(dst_cols, nxt.key))
        sql += f"\nJOIN {adapter.qualify(nxt.table)} AS n{i} ON {on}"
        prev_key = nxt.key
    return sql


def generate(spec: GraphSpec, adapter: Adapter, max_hops: int = 3, limit: int = 20) -> list[EvalQuery]:
    graph = adapter.graph_ref(spec.name)
    # Take short and long paths in turn, so a small limit still covers multi-hop queries.
    by_len: dict[int, list] = {}
    for p in paths(spec, max_hops):
        by_len.setdefault(len(p[1]), []).append(p)
    mixed = []
    while any(by_len.values()):
        for k in sorted(by_len):
            if by_len[k]:
                mixed.append(by_len[k].pop(0))
    out = []
    for start, steps in mixed:
        if len(out) >= limit:
            break
        via = ", ".join(s[0] for s in steps)
        end = steps[-1][3]
        pattern = _pattern(start, steps)
        joins = _sql_joins(spec, adapter, start, steps)
        qid = f"{start}-{'-'.join(s[0] for s in steps)}"
        out.append(EvalQuery(
            id=f"count:{qid}",
            question=f"How many {start} to {end} paths are there via {via}?",
            gql=f"GRAPH {graph}\nMATCH {pattern}\nRETURN COUNT(*) AS n",
            sql=f"SELECT COUNT(*) AS n\n{joins}",
            compare="count",
        ))
        if len(steps) >= 2 and len(out) < limit:
            last = len(steps)
            skey, ekey = spec.node(start).key, spec.node(end).key
            cols = ", ".join([f"n0.{k} AS start_{k}" for k in skey] + [f"n{last}.{k} AS end_{k}" for k in ekey])
            group = ", ".join(f"start_{k}" for k in skey)
            reached = "COUNT(DISTINCT " + (f"end_{ekey[0]}" if len(ekey) == 1 else
                                           "CONCAT(" + ", '|', ".join(f"CAST(end_{k} AS STRING)" for k in ekey) + ")") + ")"
            order = f"reached DESC, {group}"
            out.append(EvalQuery(
                id=f"top:{qid}",
                question=f"Which 5 {start}s reach the most different {end}s via {via}?",
                gql=(f"SELECT {group}, {reached} AS reached\nFROM GRAPH_TABLE({graph.strip()}\n"
                     f"  MATCH {pattern}\n  COLUMNS ({cols})\n)\n"
                     f"GROUP BY {group}\nORDER BY {order}\nLIMIT 5"),
                sql=(f"SELECT {group}, {reached} AS reached\nFROM (\nSELECT {cols}\n{joins}\n) AS t\n"
                     f"GROUP BY {group}\nORDER BY {order}\nLIMIT 5"),
            ))
    return out


def normalize(rows: list[dict], compare: str):
    if compare == "count":
        return int(list(rows[0].values())[0]) if rows else 0

    def norm(v):
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)
    return [tuple(norm(v) for v in r.values()) for r in rows]
