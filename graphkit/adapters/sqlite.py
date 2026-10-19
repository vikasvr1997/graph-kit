"""SQLite source, for the offline demo and tests.

It can scan and run SQL, but SQLite has no graph engine, so GQL queries
raise GraphNotSupported. Use BigQuery or Spanner for real graphs.
"""
from __future__ import annotations

import re
import sqlite3

from .base import Adapter, Column, ForeignKey, GraphNotSupported, QueryResult, TableInfo

_TYPES = {"INT": "INT64", "REAL": "FLOAT64", "FLOA": "FLOAT64", "DOUB": "FLOAT64", "TEXT": "STRING",
          "CHAR": "STRING", "BOOL": "BOOL", "DATE": "DATE", "BLOB": "BYTES"}


def _norm(t: str) -> str:
    t = (t or "").upper()
    return next((v for k, v in _TYPES.items() if k in t), "OTHER" if t else "STRING")


class SqliteAdapter(Adapter):
    backend = "sqlite"
    supports_graph = False

    def __init__(self, location: dict):
        super().__init__(location)
        self.conn = sqlite3.connect(location["path"], check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Optional descriptions live in a side table, since SQLite has no comments.
        self._desc = {}
        if "_descriptions" in self._all_tables():
            for r in self.conn.execute("SELECT table_name, column_name, description FROM _descriptions"):
                self._desc[(r[0], r[1] or "")] = r[2]

    def _all_tables(self):
        q = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        return [r[0] for r in self.conn.execute(q)]

    def list_tables(self):
        return [t for t in self._all_tables() if not t.startswith("_") and not t.lower().startswith("graphkitsemantic_")]

    def describe(self, table):
        cols, pk = [], []
        for r in self.conn.execute(f'PRAGMA table_info("{table}")'):
            cols.append(Column(r["name"], _norm(r["type"]), self._desc.get((table, r["name"]), "")))
            if r["pk"]:
                pk.append((r["pk"], r["name"]))
        fks: dict[int, ForeignKey] = {}
        for r in self.conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            fk = fks.setdefault(r["id"], ForeignKey([], r["table"], []))
            fk.columns.append(r["from"])
            fk.ref_columns.append(r["to"])
        return TableInfo(
            name=table,
            columns=cols,
            description=self._desc.get((table, ""), ""),
            primary_key=[c for _, c in sorted(pk)],
            foreign_keys=list(fks.values()),
        )

    def sample(self, table, n):
        return [dict(r) for r in self.conn.execute(f'SELECT * FROM "{table}" LIMIT ?', (n,))]

    def count_matches(self, table, column, values):
        values = sorted({str(v) for v in values if v is not None})
        if not values:
            return 0
        marks = ",".join("?" * len(values))
        q = f'SELECT COUNT(DISTINCT CAST("{column}" AS TEXT)) FROM "{table}" WHERE CAST("{column}" AS TEXT) IN ({marks})'
        return self.conn.execute(q, values).fetchone()[0]

    def qualify(self, table):
        return f'"{table}"'

    def run(self, sql, params=None):
        if re.match(r"\s*GRAPH\b", sql, re.I):
            raise GraphNotSupported("SQLite can't run graph queries. Use BigQuery or Spanner.")
        rows, ms = self._timed(lambda: [dict(r) for r in self.conn.execute(sql, params or {})])
        return QueryResult(rows=rows, elapsed_ms=ms)

    def run_readonly(self, sql, max_rows=50):
        # A separate connection prevents changing the scanner's connection state.
        from pathlib import Path
        uri = Path(self.location['path']).resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only = ON')
            # Bound runaway joins independently of returned row count.
            import time
            deadline = time.monotonic() + 10
            conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows, ms = self._timed(lambda: [dict(r) for r in conn.execute(sql).fetchmany(max_rows + 1)])
        return QueryResult(rows=rows, elapsed_ms=ms)
