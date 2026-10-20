"""What every data source must provide so the kit can scan it and query it."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    type: str  # normalized: STRING, INT64, FLOAT64, BOOL, DATE, TIMESTAMP, BYTES, OTHER
    description: str = ""


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


@dataclass
class TableInfo:
    name: str
    columns: list[Column]
    description: str = ""
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    parent_table: str = ""  # Spanner interleaving
    sample: list[dict] = field(default_factory=list)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass
class QueryResult:
    rows: list[dict]
    elapsed_ms: float  # wall-clock time seen by the caller
    server_ms: float | None = None  # time the database reports, when it does
    bytes_processed: int | None = None


class GraphNotSupported(RuntimeError):
    """Raised when a source can run SQL but not graph (GQL) queries."""


class Adapter:
    backend = "base"
    supports_graph = False  # can this source run GQL queries?

    def __init__(self, location: dict):
        self.location = location

    # ---- scanning ----
    def list_tables(self) -> list[str]:
        raise NotImplementedError

    def describe(self, table: str) -> TableInfo:
        """Columns, descriptions and declared keys. No data."""
        raise NotImplementedError

    def sample(self, table: str, n: int) -> list[dict]:
        """Up to n rows. Should be cheap: never a full-table scan when avoidable."""
        raise NotImplementedError

    def count_matches(self, table: str, column: str, values: list) -> int:
        """How many of `values` appear in table.column. Used to check a guessed link."""
        values = sorted({str(v) for v in values if v is not None})
        if not values:
            return 0
        rows = self.run(self.match_sql(table, column), params={"vals": values}).rows
        return int(list(rows[0].values())[0]) if rows else 0

    def match_sql(self, table: str, column: str) -> str:
        return (
            f"SELECT COUNT(DISTINCT CAST({column} AS STRING)) AS n FROM {self.qualify(table)} "
            f"WHERE CAST({column} AS STRING) IN UNNEST(@vals)"
        )

    # ---- querying ----
    def qualify(self, table: str) -> str:
        """Table name as it must appear in SQL."""
        return table

    def graph_ref(self, graph: str) -> str:
        """Graph name as it must appear after GRAPH in a query."""
        return graph

    def run(self, sql: str, params: dict | None = None) -> QueryResult:
        raise NotImplementedError

    def run_readonly(self, sql: str, max_rows: int = 50) -> QueryResult:
        """Execute with database-enforced read-only behavior, returning at most limit+1 rows.

        Custom adapters must explicitly implement this contract.
        """
        raise NotImplementedError("Adapter has no read-only execution implementation.")

    def _timed(self, fn):
        start = time.perf_counter()
        out = fn()
        return out, (time.perf_counter() - start) * 1000


def scan(adapter: Adapter, sample_rows: int = 100, tables: list[str] | None = None) -> list[TableInfo]:
    """Read metadata and a small sample from every table (or just `tables`)."""
    infos = []
    for name in tables or adapter.list_tables():
        info = adapter.describe(name)
        info.sample = adapter.sample(name, sample_rows) if sample_rows else []
        infos.append(info)
    return infos
