"""BigQuery source. Needs: pip install "graphkit[bigquery]".

location keys:
  project       project that runs (and pays for) queries
  dataset       dataset to scan; the graph is created here too
  data_project  project that holds the dataset (default: project)
  max_bytes_billed  safety cap per query (default 1 GB)
"""
from __future__ import annotations

import datetime as dt

from .base import Adapter, Column, ForeignKey, QueryResult, TableInfo

_TYPES = {"INTEGER": "INT64", "INT64": "INT64", "FLOAT": "FLOAT64", "FLOAT64": "FLOAT64",
          "STRING": "STRING", "BOOLEAN": "BOOL", "BOOL": "BOOL", "DATE": "DATE",
          "TIMESTAMP": "TIMESTAMP", "DATETIME": "DATETIME", "NUMERIC": "NUMERIC",
          "BIGNUMERIC": "NUMERIC", "BYTES": "BYTES"}


class BigQueryAdapter(Adapter):
    backend = "bigquery"
    supports_graph = True

    def __init__(self, location: dict, client=None):
        super().__init__(location)
        if client is None:
            from google.cloud import bigquery
            client = bigquery.Client(project=location["project"])
        self.client = client
        self.data_project = location.get("data_project") or location["project"]
        self.dataset = location["dataset"]
        self.max_bytes = int(location.get("max_bytes_billed", 1024**3))

    def _ref(self, table):
        return f"{self.data_project}.{self.dataset}.{table}"

    def list_tables(self):
        items = self.client.list_tables(f"{self.data_project}.{self.dataset}")
        return sorted(t.table_id for t in items if t.table_type == "TABLE" and not t.table_id.lower().startswith("graphkitsemantic_"))

    def describe(self, table):
        t = self.client.get_table(self._ref(table))
        cols = [
            Column(f.name, _TYPES.get(f.field_type, "OTHER") if f.mode != "REPEATED" else "OTHER", f.description or "")
            for f in t.schema
        ]
        pk, fks = [], []
        tc = getattr(t, "table_constraints", None)
        if tc is not None:
            if tc.primary_key:
                pk = list(tc.primary_key.columns)
            for fk in tc.foreign_keys or []:
                fks.append(ForeignKey(
                    columns=[c.referencing_column for c in fk.column_references],
                    ref_table=fk.referenced_table.table_id,
                    ref_columns=[c.referenced_column for c in fk.column_references],
                ))
        return TableInfo(name=table, columns=cols, description=t.description or "", primary_key=pk, foreign_keys=fks)

    def sample(self, table, n):
        # list_rows reads storage directly: free, and no full-table query.
        return [dict(r.items()) for r in self.client.list_rows(self._ref(table), max_results=n)]

    def qualify(self, table):
        return f"`{self._ref(table)}`"

    def graph_ref(self, graph):
        return f"`{self._ref(graph)}`"

    def run(self, sql, params=None):
        from google.cloud import bigquery

        qp = []
        for name, value in (params or {}).items():
            if isinstance(value, (list, tuple)):
                qp.append(bigquery.ArrayQueryParameter(name, "STRING", [str(v) for v in value]))
            else:
                kind = {bool: "BOOL", int: "INT64", float: "FLOAT64"}.get(type(value), "STRING")
                qp.append(bigquery.ScalarQueryParameter(name, kind, value))
        config = bigquery.QueryJobConfig(
            query_parameters=qp, maximum_bytes_billed=self.max_bytes, use_query_cache=False
        )

        def go():
            job = self.client.query(sql, job_config=config)
            return job, [dict(r.items()) for r in job.result()]

        (job, rows), ms = self._timed(go)
        server = None
        if isinstance(job.started, dt.datetime) and isinstance(job.ended, dt.datetime):
            server = (job.ended - job.started).total_seconds() * 1000
        return QueryResult(rows=rows, elapsed_ms=ms, server_ms=server, bytes_processed=job.total_bytes_processed)

    def run_readonly(self, sql, max_rows=50):
        from google.cloud import bigquery
        # Dry-run identifies the server-parsed statement before execution.
        check = self.client.query(sql, job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, maximum_bytes_billed=self.max_bytes))
        if check.statement_type != 'SELECT':
            raise ValueError('Only SELECT statements may execute in the dataset agent.')
        def execute():
            job = self.client.query(sql, job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=self.max_bytes, job_timeout_ms=30000, use_query_cache=self.location.get("use_query_cache", True)))
            try:
                return [dict(r.items()) for r in job.result(timeout=30, max_results=max_rows + 1)]
            except TimeoutError:
                job.cancel()
                raise
        rows, ms = self._timed(execute)
        return QueryResult(rows=rows, elapsed_ms=ms)
