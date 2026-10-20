import pytest

from graphkit.core.ddl import create_graph_ddl
from graphkit.core.model import Edge, GraphSpec, Node, diff
from graphkit.core.terraform import write_terraform


def small(backend="bigquery"):
    loc = {"project": "p", "dataset": "d"} if backend == "bigquery" else {"project": "p", "instance": "i", "database": "db"}
    return GraphSpec(
        name="G", backend=backend, location=loc,
        nodes=[Node("Supplier", "suppliers", ["supplier_id"]), Node("Part", "parts", ["part_id"], properties=["name"])],
        edges=[Edge("MAKES", "parts", ["part_id"], "Supplier", ["supplier_id"], "Part", ["part_id"],
                    bidirectional=True, reverse_label="MADE_BY")],
    )


def test_bigquery_ddl():
    sql = create_graph_ddl(small())
    assert sql.startswith("CREATE OR REPLACE PROPERTY GRAPH `p.d.G`")
    assert "`p.d.suppliers` AS Supplier\n      KEY (supplier_id)" in sql
    assert "LABEL Part PROPERTIES (name)" in sql
    assert "SOURCE KEY (supplier_id) REFERENCES Supplier (supplier_id)" in sql
    # Two-way edge: the reverse swaps source and destination.
    rev = sql.split("AS MADE_BY")[1]
    assert "SOURCE KEY (part_id) REFERENCES Part (part_id)" in rev
    assert "DESTINATION KEY (supplier_id) REFERENCES Supplier (supplier_id)" in rev


def test_spanner_ddl_uses_bare_names():
    sql = create_graph_ddl(small("spanner"))
    assert sql.startswith("CREATE OR REPLACE PROPERTY GRAPH G")
    assert "`suppliers` AS Supplier" in sql


def test_invalid_spec_is_refused():
    spec = small()
    spec.edges[0].dest = "Nope"
    spec.nodes.append(Node("Part", "parts2", []))
    with pytest.raises(ValueError) as e:
        create_graph_ddl(spec)
    msg = str(e.value)
    assert "unknown node 'Nope'" in msg and "used more than once" in msg and "key column" in msg


def test_terraform_bigquery(tmp_path):
    out = write_terraform(small(), tmp_path)
    main = (out / "main.tf").read_text()
    assert 'resource "google_bigquery_job" "property_graph"' in main
    assert "sha256(local.ddl)" in main and 'create_disposition = ""' in main
    assert (out / "graph.sql").read_text().startswith("CREATE OR REPLACE PROPERTY GRAPH")


def test_terraform_spanner(tmp_path):
    main = (write_terraform(small("spanner"), tmp_path) / "main.tf").read_text()
    assert "gcloud spanner databases ddl update db --instance=i --project=p" in main


def test_diff():
    a, b = small(), small()
    b.edges[0].bidirectional = False
    b.nodes.append(Node("Plant", "plants", ["plant_id"]))
    assert diff(a, b) == {"added": ["node:Plant"], "removed": [], "changed": ["edge:MAKES"]}
