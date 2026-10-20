import json

from graphkit.benchmarking import generator as queries, runner as bench
from graphkit.adapters.base import QueryResult
from graphkit.adapters.sqlite import SqliteAdapter


class FakeGraphEngine(SqliteAdapter):
    """Pretends to run GQL by running a given SQL instead, so the bench can be tested offline."""
    supports_graph = True

    def __init__(self, location, answers):
        super().__init__(location)
        self.answers = answers  # gql text -> sql text that stands in for it

    def run(self, sql, params=None):
        if sql in self.answers:
            rows = [dict(r) for r in self.conn.execute(self.answers[sql])]
            return QueryResult(rows=rows, elapsed_ms=0.1)
        return super().run(sql, params)


def test_generated_sql_runs_and_counts_paths(demo):
    adapter, _, spec = demo
    qs = queries.generate(spec, adapter, max_hops=3, limit=30)
    assert {len(q.id.split("-")) for q in qs} >= {2, 3, 4}  # 1, 2 and 3 hops all present
    for q in qs:
        adapter.run(q.sql)  # every generated SQL query is valid
    usage = next(q for q in qs if q.id == "count:Part-PART_USAGE")
    n = adapter.run(usage.sql).rows[0]["n"]
    assert n == adapter.run("SELECT COUNT(*) AS n FROM part_usage").rows[0]["n"]
    assert usage.gql.startswith("GRAPH SupplyChain\nMATCH (n0:Part)-[:PART_USAGE]->(n1:VehicleModel)")


def test_two_way_edges_generate_both_directions(demo):
    adapter, _, spec = demo
    e = next(e for e in spec.edges if e.label == "HAS_SUPPLIER")
    e.bidirectional, e.reverse_label = True, "MAKES"
    ids = {q.id for q in queries.generate(spec, adapter, limit=200)}
    assert "count:Supplier-MAKES" in ids and "count:Part-HAS_SUPPLIER" in ids
    # Never walks the same link back and forth.
    assert not any("HAS_SUPPLIER-MAKES" in i or "MAKES-HAS_SUPPLIER" in i for i in ids)


def test_bench_matches_and_saves_examples(demo, tmp_path):
    adapter, _, spec = demo
    qs = queries.generate(spec, adapter, limit=8)
    engine = FakeGraphEngine(adapter.location, {q.gql: q.sql for q in qs})
    results = bench.run_bench(engine, qs, repeat=2)
    assert all(r.match for r in results)
    files = bench.save(results, qs, tmp_path)
    assert len(json.loads(files["examples"].read_text())) == len(qs)
    assert bench.summary(results)["matched"] == len(qs)


def test_bench_catches_a_wrong_graph(demo):
    adapter, _, spec = demo
    qs = queries.generate(spec, adapter, limit=3)
    wrong = {q.gql: "SELECT 999 AS n" for q in qs}  # a graph wired to the wrong key would disagree
    results = bench.run_bench(FakeGraphEngine(adapter.location, wrong), qs, repeat=1)
    assert [r.match for r in results] == [False] * 3


def test_sqlite_runs_sql_only(demo):
    adapter, _, spec = demo
    (r,) = bench.run_bench(adapter, queries.generate(spec, adapter, limit=1), repeat=1)
    assert r.match is None and r.sql_ms is not None and "no graph engine" in r.error
