import json
from pathlib import Path
from types import SimpleNamespace as NS

from streamlit.testing.v1 import AppTest

from graphkit.agents import llm
from graphkit.core import workflow
from graphkit.adk import graph_tools, is_read_only_graph_query, prompt_snippet


def test_read_only_guard():
    assert is_read_only_graph_query("GRAPH g MATCH (a:A) RETURN a.id")
    assert is_read_only_graph_query("SELECT x FROM GRAPH_TABLE(g MATCH (a:A) COLUMNS (a.id AS x));")
    assert not is_read_only_graph_query("SELECT * FROM t")
    assert not is_read_only_graph_query("GRAPH g MATCH (a) RETURN a; DROP TABLE t")
    assert not is_read_only_graph_query("DELETE FROM t WHERE true -- GRAPH")
    assert not is_read_only_graph_query("CREATE OR REPLACE PROPERTY GRAPH g NODE TABLES (t)")


def test_tools_and_prompt_snippet(tmp_path, demo_db):
    ws = workflow.Workspace(tmp_path, "SupplyChain")
    spec, _ = workflow.do_scan(ws, "sqlite", {"path": str(demo_db)})
    workflow.confirm(ws, spec)
    (ws.dir / "examples.json").write_text(json.dumps([{"question": "Q1?", "gql": "GRAPH SupplyChain MATCH ..."}]))
    describe_graph, run_graph_query = graph_tools(ws.approved_path)
    info = describe_graph()
    assert {"from": "Part", "to": "Supplier", "label": "HAS_SUPPLIER", "table": "parts"} in info["edges"]
    assert run_graph_query("DROP TABLE parts")["status"] == "error"
    # SQLite has no graph engine; the error comes back to the model instead of raising.
    assert "graph" in run_graph_query("GRAPH SupplyChain MATCH (p:Part) RETURN COUNT(*) AS n")["error"]
    text = prompt_snippet(ws.dir)
    assert "(Part)-[:HAS_SUPPLIER]->(Supplier)" in text and "Q1?" in text


class FakeGemini:
    def __init__(self, answer):
        self.models = NS(generate_content=lambda **kw: NS(text=json.dumps(answer)))


def test_llm_refine_applies_safe_suggestions(demo):
    _, tables, spec = demo
    answer = {"nodes": [{"label": "VehicleModel", "new_label": "Model"}],
              "edges": [{"label": "PART_USAGE", "new_label": "USED_IN"},
                        {"label": "HAS_SUPPLIER", "new_label": "MADE_BY", "bidirectional": True, "reverse_label": "MAKES"},
                        {"label": "RECALL_PARTS", "new_label": "bad label!"},
                        {"label": "SHIPMENTS", "flip": True}]}
    out, changes = llm.refine(spec, tables, client=FakeGemini(answer))
    e = {x.label: x for x in out.edges}
    assert e["USED_IN"].dest == "Model"
    assert e["MADE_BY"].bidirectional and e["MADE_BY"].reverse_label == "MAKES"
    assert "RECALL_PARTS" in e  # invalid label ignored
    assert (e["SHIPMENTS"].source, e["SHIPMENTS"].source_key) == ("Plant", ["plant_id"])
    assert out.validate() == [] and len(changes) == 5


def test_llm_eval_queries(demo):
    adapter, tables, spec = demo
    answer = {"queries": [{"question": "q", "gql": "GRAPH SupplyChain MATCH (a:Part) RETURN COUNT(*) AS n",
                           "sql": "SELECT COUNT(*) AS n FROM parts"}, {"question": "no sql", "gql": "x"}]}
    (q,) = llm.eval_queries(spec, tables, adapter, client=FakeGemini(answer))
    assert q.source == "llm" and q.compare == "rows"


APP = str(Path(__file__).parents[1] / "graphkit" / "ui" / "app.py")


def test_ui_scan_save_and_confirm(tmp_path, demo_db, monkeypatch):
    monkeypatch.setenv("GRAPHKIT_HOME", str(tmp_path / "out"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.text_input[0].set_value(str(demo_db)).run()
    next(b for b in at.button if b.label == "Scan tables").click().run()
    assert not at.exception
    assert [m.value for m in at.metric][:2] == ["5", "6"]

    next(b for b in at.button if b.label == "Save draft").click().run()  # unchanged edit round-trips
    assert not at.exception and not at.warning
    ws = workflow.Workspace(tmp_path / "out", "SupplyChain")
    assert len(ws.draft().edges) == 6

    next(c for c in at.checkbox if c.label.startswith("I reviewed")).check().run()
    next(b for b in at.button if b.label == "Confirm and write Terraform").click().run()
    assert not at.exception
    assert ws.approved() is not None
