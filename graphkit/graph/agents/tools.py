"""Plug a graph into any agent (Google ADK or anything that takes Python functions as tools).

    from graphkit.adk import graph_tools, prompt_snippet
    tools = graph_tools("graphkit_out/SupplyChain/approved.json")
    agent = Agent(..., instruction=BASE + prompt_snippet("graphkit_out/SupplyChain"), tools=tools)

The query tool only runs read-only graph queries and returns at most
`max_rows` rows. BigQuery queries also keep the adapter's bytes-billed cap.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from graphkit.graph.adapters import Adapter
from graphkit.graph.adapters import open_adapter
from graphkit.graph.core.ddl import graph_name
from graphkit.graph.core.model import GraphSpec

_WRITE = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CALL|EXPORT|LOAD|EXECUTE)\b", re.I)
_TOKENS = re.compile(
    r"'(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|`(?:``|\\.|[^`])*`|--[^\n]*|/\*.*?\*/",
    re.S,
)


def query_parts(query: str, *, graph_labels: bool = False) -> tuple[str, str]:
    """Preserve executable text, but mask literals/identifiers for keyword checks.

    GQL labels such as :Load name schema objects, not write operations. This is
    a conservative precheck; adapters still enforce read-only execution.
    """
    body = _TOKENS.sub(lambda m: ' ' if m[0].startswith(('--', '/*')) else m[0], query).strip()
    if body.endswith(';'):
        body = body[:-1].rstrip()
    scrubbed = _TOKENS.sub(' ', body)
    if graph_labels:
        scrubbed = re.sub(r':\s*[A-Za-z_][A-Za-z0-9_]*', ':label', scrubbed)
    return body, scrubbed


def is_read_only_graph_query(q: str) -> bool:
    body, scrubbed = query_parts(q, graph_labels=True)
    if ";" in scrubbed or _WRITE.search(scrubbed):
        return False
    return bool(re.match(r"GRAPH\b", body, re.I) or (re.match(r"(SELECT|WITH)\b", body, re.I) and "GRAPH_TABLE" in body.upper()))


def _load(spec: GraphSpec | str | Path) -> GraphSpec:
    return spec if isinstance(spec, GraphSpec) else GraphSpec.load(spec)


def describe(spec: GraphSpec, adapter: Adapter | None = None) -> dict:
    graph = adapter.graph_ref(spec.name) if adapter else graph_name(spec)
    return {
        "graph": graph,
        "nodes": [{"label": n.label, "key": n.key, "table": n.table, "description": n.description} for n in spec.nodes],
        "edges": [{"label": lbl, "from": (e.dest if rev else e.source), "to": (e.source if rev else e.dest),
                   "table": e.table} for lbl, e, rev in spec.directed_edges()],
    }


def prompt_snippet(graph_dir: str | Path, max_examples: int = 6) -> str:
    """Text for an agent's instruction: the graph's shape plus verified example queries."""
    d = Path(graph_dir)
    spec = GraphSpec.load(d / "approved.json")
    info = describe(spec)
    lines = [f"Property graph {info['graph']} (start queries with GRAPH {info['graph']}):", "Nodes:"]
    lines += [f"- ({n['label']}) key {', '.join(n['key'])}. {n['description']}".rstrip() for n in info["nodes"]]
    lines.append("Edges:")
    lines += [f"- ({e['from']})-[:{e['label']}]->({e['to']})" for e in info["edges"]]
    ex = d / "examples.json"
    if ex.exists():
        examples = json.loads(ex.read_text())[:max_examples]
        if examples:
            lines.append("Verified example queries:")
            for e in examples:
                lines.append(f"Q: {e['question']}\n{e['gql']}")
    return "\n".join(lines)


def graph_tools(spec: GraphSpec | str | Path, adapter: Adapter | None = None, max_rows: int = 50) -> list:
    spec = _load(spec)
    adapter = adapter or open_adapter(spec.backend, spec.location)

    def describe_graph() -> dict:
        """Returns the graph's node labels, edge labels and how they connect."""
        return describe(spec, adapter)

    def run_graph_query(query: str) -> dict:
        """Runs one read-only graph query (GQL starting with GRAPH, or SELECT ... GRAPH_TABLE)
        and returns up to 50 rows.

        Args:
            query: The GQL query, for example
                GRAPH my_graph MATCH (s:Supplier)-[:SUPPLIES]->(p:Part) RETURN s.name, COUNT(*) AS parts GROUP BY s.name
        """
        if not is_read_only_graph_query(query):
            return {"status": "error", "error": "Only one read-only graph query is allowed."}
        try:
            res = adapter.run(query)
        except Exception as e:  # noqa: BLE001 - the model should see the error and fix its query
            return {"status": "error", "error": str(e)[:800]}
        return {"status": "success", "rows": res.rows[:max_rows], "truncated": len(res.rows) > max_rows,
                "elapsed_ms": round(res.elapsed_ms)}

    return [describe_graph, run_graph_query]


def dataset_tools(workspace, *, ask, embed_question, embedding_model, adapter=None):
    """Create an ADK-compatible question tool from reviewed catalog artifacts.

    Reuses the inner DatasetAgent; the embedding/model providers are injected so
    the outer agent and query generator can be configured independently.
    """
    from graphkit.graph.agents.dataset_agent import DatasetAgent
    dataset = DatasetAgent(workspace, ask, embed_question, embedding_model, adapter)

    def answer_dataset_question(question: str) -> dict:
        """Answer a question using the approved dataset and return query evidence."""
        return dataset.answer(question)

    return [answer_dataset_question]
