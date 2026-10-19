"""Graph kit UI: scan, see the graph, edit it, confirm, apply, benchmark.

    graphkit ui                  # or: streamlit run graphkit/ui/app.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from graphkit import workflow
from graphkit.adapters import open_adapter
from graphkit.ddl import create_graph_ddl
from graphkit.model import APPROVED, NEW, PROPOSED, Edge, GraphSpec, Node
from graphkit.terraform import terraform_available
from graphkit.ui.graph_view import colors, data_view, render, schema_view

st.set_page_config(page_title="Graph kit", page_icon="🕸️", layout="wide")
ROOT = Path(os.getenv("GRAPHKIT_HOME", "graphkit_out"))
STATUSES = [PROPOSED, NEW, APPROVED]


def split(s) -> list[str]:
    return [x.strip() for x in str(s or "").split(",") if x.strip()]


def join(xs) -> str:
    return ", ".join(xs or [])


# ---------------- sidebar: where to scan ----------------
with st.sidebar:
    st.title("🕸️ Graph kit")
    st.caption("Find links between tables, review them, and turn them into a property graph.")
    source = st.radio("Source", ["Demo (SQLite)", "BigQuery", "Spanner"], horizontal=False)
    if source == "BigQuery":
        backend = "bigquery"
        location = {
            "project": st.text_input("Project (runs queries)", os.getenv("GOOGLE_CLOUD_PROJECT", "")),
            "dataset": st.text_input("Dataset", "vehicle_supply_chain"),
            "region": st.text_input("Dataset location", "US"),
        }
        data_project = st.text_input("Data project (if different)", "")
        if data_project:
            location["data_project"] = data_project
    elif source == "Spanner":
        backend = "spanner"
        location = {
            "project": st.text_input("Project", os.getenv("GOOGLE_CLOUD_PROJECT", "")),
            "instance": st.text_input("Instance", ""),
            "database": st.text_input("Database", ""),
        }
    else:
        backend = "sqlite"
        location = {"path": st.text_input("SQLite file", "demo/supply_chain.db")}
        if not Path(location["path"]).exists() and st.button("Create demo data"):
            from graphkit.demo import make
            make(Path(location["path"]).parent)
            st.rerun()

    name = st.text_input("Graph name", "SupplyChain")
    with st.expander("Scan options"):
        sample_rows = st.slider("Rows to sample per table", 10, 1000, 100, step=10)
        check_values = st.checkbox("Check guessed links with small queries", True,
                                   help="Runs one small COUNT query per guessed link to see if the values really match.")
        desc_file = st.text_input("Extra descriptions file (JSON, optional)", "")
        use_llm = st.checkbox("Ask Gemini to improve names and directions", False,
                              help="Needs google-genai and Vertex AI access.")
    ws = workflow.Workspace(ROOT, name)
    if st.button("Scan tables", type="primary", use_container_width=True):
        with st.spinner("Reading tables and sampling rows..."):
            try:
                spec, notes = workflow.do_scan(ws, backend, location, sample_rows=sample_rows,
                                               descriptions_file=desc_file or None,
                                               check_values=check_values, use_llm=use_llm)
                st.session_state.pop("editor_version", None)
                st.success(f"Found {len(spec.nodes)} nodes and {len(spec.edges)} edges.")
            except Exception as e:  # noqa: BLE001 - show any source error to the user
                st.error(f"Scan failed: {e}")
    if ws.approved() and st.button("Look for new tables", use_container_width=True):
        with st.spinner("Re-scanning..."):
            try:
                new = workflow.do_watch(ws, sample_rows=sample_rows, check_values=check_values)
                st.info(f"{len(new)} new items to review: {', '.join(new)}" if new else "No new tables or links.")
            except Exception as e:  # noqa: BLE001
                st.error(f"Watch failed: {e}")
    st.caption(f"Files: `{ws.dir}`")


spec = ws.draft()
if spec is None:
    st.header("Start with a scan")
    st.write("Pick a source in the sidebar and press **Scan tables**. The demo uses a small made-up "
             "supply-chain dataset, so it works without a cloud account.")
    st.stop()

tables = ws.load_scan()
approved = ws.approved()
problems = spec.validate()
waiting = [x.label for x in spec.nodes + spec.edges if x.status != APPROVED]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Nodes", len(spec.nodes))
c2.metric("Edges", len(spec.directed_edges()))
c3.metric("Waiting for review", len(waiting))
c4.metric("Problems", len(problems))

tab_graph, tab_edit, tab_apply, tab_bench = st.tabs(["Graph", "Edit", "Review and apply", "Benchmark"])

# ---------------- graph ----------------
with tab_graph:
    view = st.segmented_control("View", ["Schema", "Data preview"], default="Schema")
    if view == "Data preview":
        per = st.slider("Rows per node type", 3, 50, 8)
        nodes, edges = data_view(spec, tables, per)
        components.html(render(nodes, edges, colors(spec), height=620, big=False), height=660)
    else:
        nodes, edges = schema_view(spec)
        components.html(render(nodes, edges, colors(spec)), height=600)
    notes = ws.notes()
    if notes:
        with st.expander(f"Scan notes ({len(notes)})"):
            for n in notes:
                st.write(f"- {n}")

# ---------------- edit ----------------
with tab_edit:
    st.caption("Add a row to create, edit a cell to update, or select rows and press Delete to remove. "
               "Keys are comma-separated column names. Nothing is applied until you confirm.")
    table_names = sorted({t.name for t in tables} | spec.tables())
    labels = [n.label for n in spec.nodes]
    version = st.session_state.setdefault("editor_version", 0)

    node_df = pd.DataFrame([{"label": n.label, "table": n.table, "key": join(n.key),
                             "properties": "" if n.properties is None else join(n.properties),
                             "description": n.description, "status": n.status} for n in spec.nodes],
                           columns=["label", "table", "key", "properties", "description", "status"])
    st.subheader("Nodes")
    node_out = st.data_editor(node_df, num_rows="dynamic", use_container_width=True, key=f"nodes{version}",
                              column_config={
                                  "table": st.column_config.SelectboxColumn(options=table_names, required=True),
                                  "properties": st.column_config.TextColumn(help="Blank = all columns"),
                                  "status": st.column_config.SelectboxColumn(options=STATUSES, default=PROPOSED),
                              })

    edge_df = pd.DataFrame([{"label": e.label, "table": e.table, "key": join(e.key), "source": e.source,
                             "source_key": join(e.source_key), "dest": e.dest, "dest_key": join(e.dest_key),
                             "two_way": e.bidirectional, "reverse_label": e.reverse_label,
                             "confidence": e.confidence, "why": e.reason, "status": e.status} for e in spec.edges],
                           columns=["label", "table", "key", "source", "source_key", "dest", "dest_key",
                                    "two_way", "reverse_label", "confidence", "why", "status"])
    st.subheader("Edges")
    label_opts = sorted(set(labels) | set(node_out["label"].dropna()))
    edge_out = st.data_editor(edge_df, num_rows="dynamic", use_container_width=True, key=f"edges{version}",
                              column_config={
                                  "table": st.column_config.SelectboxColumn(options=table_names, required=True),
                                  "source": st.column_config.SelectboxColumn(options=label_opts, required=True),
                                  "dest": st.column_config.SelectboxColumn(options=label_opts, required=True),
                                  "two_way": st.column_config.CheckboxColumn(help="Also add a reverse edge", default=False),
                                  "reverse_label": st.column_config.TextColumn(help="e.g. SUPPLIED_BY"),
                                  "confidence": st.column_config.NumberColumn(format="%.2f", disabled=True),
                                  "why": st.column_config.TextColumn(disabled=True, width="large"),
                                  "status": st.column_config.SelectboxColumn(options=STATUSES, default=PROPOSED),
                              })

    flip = st.multiselect("Flip direction of", list(edge_out["label"].dropna()))
    if st.button("Save draft", type="primary"):
        new_nodes = [Node(label=str(r.label), table=str(r.table), key=split(r.key),
                          properties=split(r.properties) or None, description=str(r.description or ""),
                          status=str(r.status or PROPOSED))
                     for r in node_out.itertuples() if pd.notna(r.label) and str(r.label).strip()]
        new_edges = []
        for r in edge_out.itertuples():
            if pd.isna(r.label) or not str(r.label).strip():
                continue
            e = Edge(label=str(r.label), table=str(r.table), key=split(r.key), source=str(r.source),
                     source_key=split(r.source_key), dest=str(r.dest), dest_key=split(r.dest_key),
                     bidirectional=bool(r.two_way), reverse_label=str(r.reverse_label or "") if pd.notna(r.reverse_label) else "",
                     confidence=float(r.confidence) if pd.notna(r.confidence) else 1.0,
                     reason=str(r.why) if pd.notna(r.why) else "added in editor",
                     status=str(r.status) if pd.notna(r.status) else PROPOSED)
            if e.label in flip:
                e.source, e.dest, e.source_key, e.dest_key = e.dest, e.source, e.dest_key, e.source_key
            new_edges.append(e)
        edited = GraphSpec(name=spec.name, backend=spec.backend, location=spec.location,
                           nodes=new_nodes, edges=new_edges)
        bad = edited.validate()
        edited.save(ws.draft_path)  # keep the edit even if it still has problems
        st.session_state.editor_version = version + 1
        if bad:
            st.warning("Saved, but fix these before applying:\n- " + "\n- ".join(bad))
        else:
            st.rerun()

# ---------------- review and apply ----------------
with tab_apply:
    changes = workflow.pending_changes(ws)
    if problems:
        st.error("Fix these in the Edit tab first:\n- " + "\n- ".join(problems))
    left, right = st.columns(2)
    with left:
        st.subheader("Changes since last approval")
        if not any(changes.values()):
            st.write("No changes.")
        for kind, icon in (("added", "🟢"), ("changed", "🟡"), ("removed", "🔴")):
            for item in changes[kind]:
                st.write(f"{icon} {kind}: `{item}`")
    with right:
        st.subheader("Graph DDL")
        preview = spec
        if spec.backend == "sqlite":
            st.caption("Demo source: shown as BigQuery DDL. Scan a BigQuery or Spanner source to apply for real.")
            preview = GraphSpec.from_dict({**spec.to_dict(), "backend": "bigquery",
                                           "location": {"project": "YOUR_PROJECT", "dataset": "YOUR_DATASET"}})
        if not problems:
            st.code(create_graph_ddl(preview), language="sql")

    st.divider()
    ok = st.checkbox("I reviewed the graph and want to approve it", disabled=bool(problems))
    if st.button("Confirm and write Terraform", type="primary", disabled=not ok):
        out = workflow.confirm(ws, spec)
        st.success(f"Approved. Files written to `{out}`.")
        st.rerun()

    if approved and approved.backend in ("bigquery", "spanner") and ws.tf_dir.exists():
        st.subheader("Terraform")
        for f in ("main.tf", "graph.sql"):
            with st.expander(f):
                st.code((ws.tf_dir / f).read_text(), language="sql" if f.endswith(".sql") else "hcl")
        if not terraform_available():
            st.info(f"Terraform isn't installed here. Run it yourself:\n\n"
                    f"`terraform -chdir={ws.tf_dir} init && terraform -chdir={ws.tf_dir} apply`")
        else:
            a, b = st.columns(2)
            if a.button("Terraform plan"):
                code, log = workflow.apply(ws, "plan")
                st.code(log[-8000:])
            really = b.checkbox(f"Create the graph in {approved.location.get('project')}")
            if b.button("Apply", disabled=not really):
                with st.spinner("terraform apply..."):
                    code, log = workflow.apply(ws, "apply")
                (st.success if code == 0 else st.error)("Applied." if code == 0 else "Apply failed.")
                st.code(log[-8000:])

# ---------------- benchmark ----------------
with tab_bench:
    st.caption("Generates test questions from the graph, runs each as GQL and as plain SQL, checks the "
               "answers match, and times both. Matching queries are saved as examples an agent can reuse.")
    a, b, c, d = st.columns(4)
    hops = a.slider("Max hops", 1, 4, 3)
    limit = b.number_input("Generated queries", 1, 100, 20)
    llm_n = c.number_input("Extra Gemini questions", 0, 30, 0)
    repeat = d.number_input("Runs per query", 1, 10, 3)
    if st.button("Run benchmark", type="primary"):
        with st.spinner("Running queries..."):
            try:
                adapter = open_adapter(spec.backend, spec.location)
                workflow.do_bench(ws, adapter, max_hops=hops, limit=int(limit), llm_questions=int(llm_n),
                                  repeat=int(repeat))
            except Exception as e:  # noqa: BLE001
                st.error(f"Benchmark failed: {e}")
    bench_file = ws.dir / "bench.json"
    if bench_file.exists():
        data = json.loads(bench_file.read_text())
        s = data["summary"]
        m = st.columns(5)
        m[0].metric("Queries", s["queries"])
        m[1].metric("Answers match", f"{s['matched']}/{s['compared']}" if s["compared"] else "n/a")
        m[2].metric("GQL median", f"{s['gql_median_ms']} ms" if s["gql_median_ms"] is not None else "n/a")
        m[3].metric("SQL median", f"{s['sql_median_ms']} ms" if s["sql_median_ms"] is not None else "n/a")
        m[4].metric("Errors", s["errors"])
        df = pd.DataFrame(data["results"])
        st.dataframe(df[["question", "match", "gql_ms", "sql_ms", "faster", "rows", "gql_bytes", "error"]],
                     use_container_width=True, hide_index=True)
        if spec.backend == "sqlite":
            st.info("The demo has no graph engine, so only the SQL side ran. On BigQuery or Spanner both run.")
