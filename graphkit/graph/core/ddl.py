"""Write the CREATE PROPERTY GRAPH statement for BigQuery or Spanner.

Both use the same GQL DDL. The differences are table naming (BigQuery needs
`project.dataset.table`) and where the graph lives.
"""
from __future__ import annotations

from graphkit.graph.core.model import GraphSpec


def _table(spec: GraphSpec, table: str) -> str:
    if spec.backend == "bigquery":
        loc = spec.location
        return f"`{loc.get('data_project') or loc['project']}.{loc['dataset']}.{table}`"
    return f"`{table}`" if spec.backend == "spanner" else table


def graph_name(spec: GraphSpec) -> str:
    if spec.backend == "bigquery":
        loc = spec.location
        return f"`{loc.get('data_project') or loc['project']}.{loc['dataset']}.{spec.name}`"
    return spec.name


def _cols(cols: list[str]) -> str:
    return ", ".join(cols)


def _props(props: list[str] | None) -> str:
    return "PROPERTIES ALL COLUMNS" if props is None else f"PROPERTIES ({_cols(props)})"


def create_graph_ddl(spec: GraphSpec) -> str:
    problems = spec.validate()
    if problems:
        raise ValueError("Fix the graph before applying:\n- " + "\n- ".join(problems))

    nodes = []
    for n in spec.nodes:
        nodes.append(
            f"    {_table(spec, n.table)} AS {n.label}\n"
            f"      KEY ({_cols(n.key)})\n"
            f"      LABEL {n.label} {_props(n.properties)}"
        )
    edges = []
    for label, e, reverse in spec.directed_edges():
        src, src_key, dst, dst_key = e.source, e.source_key, e.dest, e.dest_key
        if reverse:
            src, src_key, dst, dst_key = dst, dst_key, src, src_key
        edges.append(
            f"    {_table(spec, e.table)} AS {label}\n"
            f"      KEY ({_cols(e.key)})\n"
            f"      SOURCE KEY ({_cols(src_key)}) REFERENCES {src} ({_cols(spec.node(src).key)})\n"
            f"      DESTINATION KEY ({_cols(dst_key)}) REFERENCES {dst} ({_cols(spec.node(dst).key)})\n"
            f"      LABEL {label} {_props(e.properties)}"
        )
    sql = f"CREATE OR REPLACE PROPERTY GRAPH {graph_name(spec)}\n  NODE TABLES (\n" + ",\n".join(nodes) + "\n  )"
    if edges:
        sql += "\n  EDGE TABLES (\n" + ",\n".join(edges) + "\n  )"
    return sql


def drop_graph_ddl(spec: GraphSpec) -> str:
    return f"DROP PROPERTY GRAPH IF EXISTS {graph_name(spec)}"
