"""Optional Gemini helpers. Needs: pip install "graphkit[llm]".

- refine(): reads table and column descriptions and suggests clearer edge
  labels (PART_USAGE -> USED_IN), better directions, and which links
  should go both ways. Nothing is applied until a developer confirms.
- eval_queries(): writes harder test questions, each as GQL plus the
  equivalent SQL, so the benchmark can check the graph's answers.

Uses Vertex AI by default (GOOGLE_GENAI_USE_VERTEXAI=TRUE, your gcloud login).
"""
from __future__ import annotations

import json
import os
import re

from .adapters.base import Adapter, TableInfo
from .model import GraphSpec
from .queries import EvalQuery

MODEL = os.getenv("GRAPHKIT_MODEL", "gemini-3.5-flash")
_LABEL = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _client():
    from google import genai
    return genai.Client()


def _ask(prompt: str, client=None, model: str = MODEL) -> dict:
    from google.genai import types

    client = client or _client()
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
    )
    return json.loads(resp.text)


def _schema(spec: GraphSpec, tables: list[TableInfo]) -> str:
    t = [{"table": x.name, "description": x.description,
          "columns": [{"name": c.name, "type": c.type, "description": c.description} for c in x.columns]}
         for x in tables if x.name in spec.tables()]
    g = {"nodes": [{"label": n.label, "table": n.table, "key": n.key} for n in spec.nodes],
         "edges": [{"label": e.label, "table": e.table, "source": e.source, "dest": e.dest,
                    "source_key": e.source_key, "dest_key": e.dest_key} for e in spec.edges]}
    return json.dumps({"tables": t, "graph": g}, default=str)


REFINE_PROMPT = """You are reviewing a property graph built automatically from database tables.
Using the table and column descriptions, suggest clearer names and directions.

Rules:
- Node labels: singular PascalCase nouns (Supplier, VehicleModel).
- Edge labels: UPPER_SNAKE_CASE verbs read from source to destination (SUPPLIES, USED_IN).
- Set "flip": true only if the edge reads more naturally the other way.
- Set "bidirectional": true only if people will often ask the question in both directions,
  and give "reverse_label" (e.g. SUPPLIED_BY).
- Do not invent nodes or edges.

Return JSON: {{"nodes": [{{"label": old, "new_label": ...}}],
"edges": [{{"label": old, "new_label": ..., "flip": bool, "bidirectional": bool, "reverse_label": ...}}]}}

Schema and current graph:
{schema}
"""


def refine(spec: GraphSpec, tables: list[TableInfo], client=None) -> tuple[GraphSpec, list[str]]:
    """Return a new spec with Gemini's suggestions applied, plus a list of what changed."""
    data = _ask(REFINE_PROMPT.format(schema=_schema(spec, tables)), client)
    out = GraphSpec.from_dict(spec.to_dict())
    changes = []
    taken = {n.label for n in out.nodes} | {e.label for e in out.edges}

    def ok(new, old):
        return new and new != old and _LABEL.match(new) and new not in taken

    for s in data.get("nodes", []):
        node = next((n for n in out.nodes if n.label == s.get("label")), None)
        new = s.get("new_label", "")
        if node and ok(new, node.label):
            for e in out.edges:
                e.source = new if e.source == node.label else e.source
                e.dest = new if e.dest == node.label else e.dest
            changes.append(f"Node {node.label} -> {new}")
            taken.add(new)
            node.label = new
    for s in data.get("edges", []):
        e = next((x for x in out.edges if x.label == s.get("label")), None)
        if e is None:
            continue
        new = s.get("new_label", "")
        if ok(new, e.label):
            changes.append(f"Edge {e.label} -> {new}")
            taken.add(new)
            e.label = new
        if s.get("flip"):
            e.source, e.dest = e.dest, e.source
            e.source_key, e.dest_key = e.dest_key, e.source_key
            changes.append(f"Edge {e.label} now points {e.source} -> {e.dest}")
        rev = s.get("reverse_label", "")
        if s.get("bidirectional") and not e.bidirectional and ok(rev, ""):
            e.bidirectional, e.reverse_label = True, rev
            taken.add(rev)
            changes.append(f"Edge {e.label} also goes back as {rev}")
        e.reason += " (reviewed by Gemini)"
    return out, changes


EVAL_PROMPT = """Write {n} realistic analyst questions about this property graph, from simple to
complex (multi-hop paths, aggregation, filtering). For each, give:
- "question": plain English
- "gql": a {dialect} query starting with `GRAPH {graph}` that answers it (GQL MATCH ... RETURN)
- "sql": an equivalent plain SQL query on the underlying tables, returning the same columns
  in the same order and the same ORDER BY, so the results can be compared row by row.
Table names in SQL must be written exactly like this: {example_table}.
Always ORDER BY all returned columns and LIMIT 20.

Return JSON: {{"queries": [{{"question": ..., "gql": ..., "sql": ...}}]}}

Schema and graph:
{schema}
"""


def eval_queries(spec: GraphSpec, tables: list[TableInfo], adapter: Adapter, n: int = 8, client=None) -> list[EvalQuery]:
    dialect = "BigQuery Graph" if spec.backend == "bigquery" else "Spanner Graph"
    first = spec.nodes[0].table if spec.nodes else "table"
    data = _ask(EVAL_PROMPT.format(n=n, dialect=dialect, graph=adapter.graph_ref(spec.name),
                                   example_table=adapter.qualify(first), schema=_schema(spec, tables)), client)
    out = []
    for i, q in enumerate(data.get("queries", [])[:n], 1):
        if q.get("gql") and q.get("sql"):
            out.append(EvalQuery(id=f"llm:{i}", question=q.get("question", ""), gql=q["gql"], sql=q["sql"],
                                 compare="rows", source="llm"))
    return out
