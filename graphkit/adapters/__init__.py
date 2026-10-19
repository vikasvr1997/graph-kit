"""Data sources. `open_adapter` picks one from a spec's backend and location."""
from __future__ import annotations

import json
from pathlib import Path

from .base import Adapter, Column, ForeignKey, GraphNotSupported, QueryResult, TableInfo, scan


def open_adapter(backend: str, location: dict) -> Adapter:
    if backend == "bigquery":
        from .bigquery import BigQueryAdapter
        return BigQueryAdapter(location)
    if backend == "spanner":
        from .spanner import SpannerAdapter
        return SpannerAdapter(location)
    if backend == "sqlite":
        from .sqlite import SqliteAdapter
        return SqliteAdapter(location)
    raise ValueError(f"Unknown backend {backend!r}. Use bigquery, spanner or sqlite.")


def apply_descriptions(tables: list[TableInfo], path: str | Path | None) -> None:
    """Fill in descriptions from a JSON file: {"table": {"": "table text", "col": "col text"}}.

    Useful for Spanner (no comments) or to add context a scan can't see.
    Existing descriptions win; the file only fills gaps.
    """
    if not path or not Path(path).exists():
        return
    extra = json.loads(Path(path).read_text())
    for t in tables:
        d = extra.get(t.name, {})
        t.description = t.description or d.get("", "")
        for c in t.columns:
            c.description = c.description or d.get(c.name, "")


__all__ = ["Adapter", "Column", "ForeignKey", "GraphNotSupported", "QueryResult", "TableInfo",
           "apply_descriptions", "open_adapter", "scan"]
