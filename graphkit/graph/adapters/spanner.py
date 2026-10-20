"""Spanner source (GoogleSQL dialect). Needs: pip install "graphkit[spanner]".

location keys: project, instance, database.

Spanner has no table or column comments, so descriptions come only from an
optional descriptions file (see README). Interleaved tables count as links
to their parent table.
"""
from __future__ import annotations

from graphkit.graph.adapters.base import Adapter
from graphkit.graph.adapters.base import Column
from graphkit.graph.adapters.base import ForeignKey
from graphkit.graph.adapters.base import QueryResult
from graphkit.graph.adapters.base import TableInfo


def _norm(t: str) -> str:
    t = t.upper()
    if t.startswith("ARRAY"):
        return "OTHER"
    for name in ("STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP", "BYTES", "NUMERIC"):
        if t.startswith(name):
            return name
    return "OTHER"


_FK_SQL = """
SELECT kcu.CONSTRAINT_NAME AS name, kcu.COLUMN_NAME AS col, ref.TABLE_NAME AS ref_table,
       ref.COLUMN_NAME AS ref_col, kcu.ORDINAL_POSITION AS pos
FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
  ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME AND kcu.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ref
  ON ref.CONSTRAINT_NAME = rc.UNIQUE_CONSTRAINT_NAME AND ref.CONSTRAINT_SCHEMA = rc.UNIQUE_CONSTRAINT_SCHEMA
 AND ref.ORDINAL_POSITION = kcu.POSITION_IN_UNIQUE_CONSTRAINT
WHERE rc.CONSTRAINT_SCHEMA = '' AND kcu.TABLE_NAME = @t
ORDER BY name, pos
"""


class SpannerAdapter(Adapter):
    backend = "spanner"
    supports_graph = True

    def __init__(self, location: dict, database=None):
        super().__init__(location)
        if database is None:
            from google.cloud import spanner
            client = spanner.Client(project=location["project"])
            database = client.instance(location["instance"]).database(location["database"])
        self.db = database

    def _query(self, sql, params=None):
        from google.cloud.spanner_v1 import param_types

        types = {}
        for k, v in (params or {}).items():
            if isinstance(v, (list, tuple)):
                types[k] = param_types.Array(param_types.STRING)
            elif isinstance(v, bool):
                types[k] = param_types.BOOL
            elif isinstance(v, int):
                types[k] = param_types.INT64
            elif isinstance(v, float):
                types[k] = param_types.FLOAT64
            else:
                types[k] = param_types.STRING
        with self.db.snapshot() as snap:
            result = snap.execute_sql(sql, params=params or None, param_types=types or None)
            rows = list(result)
            names = [f.name for f in result.fields]
        return [dict(zip(names, r)) for r in rows]

    def list_tables(self):
        rows = self._query(
            "SELECT TABLE_NAME AS t FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = '' AND TABLE_TYPE = 'BASE TABLE' ORDER BY t"
        )
        return [r["t"] for r in rows if not r["t"].lower().startswith(("graphkitsemantic_", "graphkitpipeline"))]

    def describe(self, table):
        cols = self._query(
            "SELECT COLUMN_NAME AS c, SPANNER_TYPE AS t FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = '' AND TABLE_NAME = @t ORDER BY ORDINAL_POSITION",
            {"t": table},
        )
        pk = self._query(
            "SELECT COLUMN_NAME AS c FROM INFORMATION_SCHEMA.INDEX_COLUMNS "
            "WHERE TABLE_SCHEMA = '' AND TABLE_NAME = @t AND INDEX_TYPE = 'PRIMARY_KEY' ORDER BY ORDINAL_POSITION",
            {"t": table},
        )
        parent = self._query(
            "SELECT PARENT_TABLE_NAME AS p FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '' AND TABLE_NAME = @t",
            {"t": table},
        )
        fks: dict[str, ForeignKey] = {}
        for r in self._query(_FK_SQL, {"t": table}):
            fk = fks.setdefault(r["name"], ForeignKey([], r["ref_table"], []))
            fk.columns.append(r["col"])
            fk.ref_columns.append(r["ref_col"])
        info = TableInfo(
            name=table,
            columns=[Column(r["c"], _norm(r["t"])) for r in cols],
            primary_key=[r["c"] for r in pk],
            foreign_keys=list(fks.values()),
            parent_table=(parent[0]["p"] or "") if parent else "",
        )
        if info.parent_table and not any(f.ref_table == info.parent_table for f in info.foreign_keys):
            # An interleaved child's key starts with its parent's key.
            parent_pk = self.describe(info.parent_table).primary_key
            info.foreign_keys.append(ForeignKey(parent_pk, info.parent_table, parent_pk))
        return info

    def sample(self, table, n):
        return self._query(f"SELECT * FROM `{table}` LIMIT {int(n)}")

    def qualify(self, table):
        return f"`{table}`"

    def run(self, sql, params=None):
        rows, ms = self._timed(lambda: self._query(sql, params))
        return QueryResult(rows=rows, elapsed_ms=ms)

    def run_readonly(self, sql, max_rows=50):
        # Snapshot execution is read-only at the database API level.
        with self.db.snapshot() as snap:
            import itertools
            def execute():
                result = snap.execute_sql(sql, timeout=30)
                rows = list(itertools.islice(result, max_rows + 1))
                names = [f.name for f in result.fields]
                return [dict(zip(names, row)) for row in rows]
            rows, ms = self._timed(execute)
        return QueryResult(rows=rows, elapsed_ms=ms)
