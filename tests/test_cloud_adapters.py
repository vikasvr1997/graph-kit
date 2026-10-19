"""BigQuery and Spanner adapters against fake clients (no cloud account needed).

These check that metadata, keys, samples and query results are read
correctly. They don't prove the SQL runs on the real services.
"""
import datetime as dt
from types import SimpleNamespace as NS

from google.cloud.bigquery import SchemaField, TableReference
from google.cloud.bigquery.table import ColumnReference, ForeignKey, PrimaryKey, TableConstraints

from graphkit.adapters.base import scan
from graphkit.adapters.bigquery import BigQueryAdapter
from graphkit.adapters.spanner import SpannerAdapter
from graphkit.infer import infer


class Row(dict):
    pass


class FakeBQ:
    def __init__(self):
        self.queries = []
        ref = TableReference.from_string("p.d.suppliers")
        self.tables = {
            "suppliers": NS(schema=[SchemaField("supplier_id", "STRING", description="Supplier code"),
                                    SchemaField("name", "STRING")],
                            description="Suppliers", table_constraints=TableConstraints(PrimaryKey(["supplier_id"]), None)),
            "parts": NS(schema=[SchemaField("part_id", "INTEGER"), SchemaField("maker", "STRING"),
                                SchemaField("tags", "STRING", mode="REPEATED")],
                        description="", table_constraints=TableConstraints(
                            PrimaryKey(["part_id"]),
                            [ForeignKey("fk", ref, [ColumnReference("maker", "supplier_id")])])),
        }
        self.rows = {"suppliers": [{"supplier_id": "S1", "name": "A"}],
                     "parts": [{"part_id": 1, "maker": "S1", "tags": []}]}

    def list_tables(self, ds):
        assert ds == "p.d"
        return [NS(table_id="suppliers", table_type="TABLE"), NS(table_id="parts", table_type="TABLE"),
                NS(table_id="v_parts", table_type="VIEW")]

    def get_table(self, ref):
        return self.tables[ref.split(".")[-1]]

    def list_rows(self, ref, max_results):
        return [Row(r) for r in self.rows[ref.split(".")[-1]][:max_results]]

    def query(self, sql, job_config):
        self.queries.append((sql, job_config))
        t0 = dt.datetime(2026, 1, 1)
        return NS(result=lambda: [Row(n=7)], started=t0, ended=t0 + dt.timedelta(milliseconds=42),
                  total_bytes_processed=1024)


def test_bigquery_reads_metadata_and_constraints():
    a = BigQueryAdapter({"project": "p", "dataset": "d"}, client=FakeBQ())
    assert a.list_tables() == ["parts", "suppliers"]  # views skipped
    parts = a.describe("parts")
    assert [c.type for c in parts.columns] == ["INT64", "STRING", "OTHER"]
    assert parts.primary_key == ["part_id"]
    (fk,) = parts.foreign_keys
    assert (fk.columns, fk.ref_table, fk.ref_columns) == (["maker"], "suppliers", ["supplier_id"])
    assert a.describe("suppliers").columns[0].description == "Supplier code"
    spec = infer(scan(a), a, name="G", backend="bigquery", location=a.location, check_values=False).spec
    assert [(e.source, e.dest, e.confidence) for e in spec.edges] == [("Part", "Supplier", 1.0)]


def test_bigquery_run_uses_cap_and_params():
    client = FakeBQ()
    a = BigQueryAdapter({"project": "p", "dataset": "d", "max_bytes_billed": 5000}, client=client)
    res = a.run("SELECT 1", params={"vals": ["a", "b"], "n": 3})
    assert res.rows == [{"n": 7}] and res.server_ms == 42 and res.bytes_processed == 1024
    _, cfg = client.queries[-1]
    assert cfg.maximum_bytes_billed == 5000 and cfg.use_query_cache is False
    assert [p.name for p in cfg.query_parameters] == ["vals", "n"]
    assert a.count_matches("suppliers", "supplier_id", ["S1", "S2"]) == 7
    assert "IN UNNEST(@vals)" in client.queries[-1][0]
    assert a.qualify("parts") == "`p.d.parts`" and a.graph_ref("G") == "`p.d.G`"


class FakeResult:
    def __init__(self, rows):
        self.rows = rows
        self.fields = [NS(name=k) for k in (rows[0] if rows else {})]

    def __iter__(self):
        return iter([list(r.values()) for r in self.rows])


class FakeSpanner:
    """orders <- order_items (interleaved) -> products (foreign key)."""
    cols = {"orders": [("order_id", "STRING(36)")], "products": [("product_id", "INT64"), ("title", "STRING(MAX)")],
            "order_items": [("order_id", "STRING(36)"), ("item_id", "INT64"), ("product_id", "INT64")]}
    pks = {"orders": ["order_id"], "products": ["product_id"], "order_items": ["order_id", "item_id"]}
    parents = {"order_items": "orders"}

    def snapshot(self):
        db = self

        class Snap:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute_sql(self, sql, params=None, param_types=None):
                t = (params or {}).get("t")
                if "TABLE_TYPE" in sql:
                    rows = [{"t": n} for n in sorted(db.cols)]
                elif "INFORMATION_SCHEMA.COLUMNS" in sql:
                    rows = [{"c": c, "t": ty} for c, ty in db.cols[t]]
                elif "INDEX_COLUMNS" in sql:
                    rows = [{"c": c} for c in db.pks[t]]
                elif "PARENT_TABLE_NAME" in sql:
                    rows = [{"p": db.parents.get(t)}]
                elif "REFERENTIAL_CONSTRAINTS" in sql:
                    rows = ([{"name": "fk_prod", "col": "product_id", "ref_table": "products", "ref_col": "product_id", "pos": 1}]
                            if t == "order_items" else [])
                elif sql.startswith("SELECT * FROM"):
                    rows = []
                else:
                    rows = [{"n": 1}]
                return FakeResult(rows)
        return Snap()


def test_spanner_reads_interleaving_and_foreign_keys():
    a = SpannerAdapter({"project": "p", "instance": "i", "database": "d"}, database=FakeSpanner())
    items = a.describe("order_items")
    assert items.primary_key == ["order_id", "item_id"] and items.parent_table == "orders"
    assert {(tuple(f.columns), f.ref_table) for f in items.foreign_keys} == {(("product_id",), "products"),
                                                                            (("order_id",), "orders")}
    spec = infer(scan(a), a, name="G", backend="spanner", location=a.location).spec
    # order_items only joins two tables, so it becomes an edge between them.
    (e,) = spec.edges
    assert (e.table, e.source, e.dest, e.key) == ("order_items", "Order", "Product", ["order_id", "item_id"])


def test_spanner_discovery_excludes_pipeline_control_tables():
    db = FakeSpanner()
    db.cols = {**db.cols, "GraphkitPipelineLock": [], "GraphkitPipelineRuns": [],
               "GraphkitSemantic_catalog": []}
    adapter = SpannerAdapter({"project": "p", "instance": "i", "database": "d"}, database=db)
    assert adapter.list_tables() == ["order_items", "orders", "products"]
