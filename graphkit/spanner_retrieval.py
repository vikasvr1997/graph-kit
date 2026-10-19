"""Exact schema-catalog retrieval inside Spanner; question embedding is external."""
from __future__ import annotations

import math
import re
from dataclasses import asdict


class SpannerCatalogRetriever:
    def __init__(self, database, table, catalog, embed_question, embedding_model, *, dimensions=768):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table):
            raise ValueError('Invalid catalog table name.')
        if not catalog.approved or dimensions < 1:
            raise ValueError('An approved catalog and positive dimensions are required.')
        self.database, self.table, self.catalog = database, table, catalog
        self.embed_question, self.model, self.dimensions = embed_question, embedding_model, dimensions

    def __call__(self, question, top_k=8):
        from google.cloud.spanner_v1 import param_types

        if not isinstance(top_k, int) or top_k < 1 or not self.catalog.items:
            raise ValueError('Invalid retrieval limit.')
        vector = self.embed_question(question)
        if (len(vector) != self.dimensions or any(not math.isfinite(x) for x in vector)
                or sum(x*x for x in vector) == 0):
            raise ValueError('Invalid question embedding dimensions or values.')
        sql = f'''SELECT item_id, COSINE_DISTANCE(embedding, @vector) AS distance
FROM `{self.table}` WHERE catalog_hash=@hash AND embedding_model=@model
ORDER BY distance, item_id LIMIT {min(top_k, len(self.catalog.items))}'''
        with self.database.snapshot() as snapshot:
            rows = list(snapshot.execute_sql(sql, params={
                'vector': vector, 'hash': self.catalog.fingerprint(), 'model': self.model},
                param_types={'vector': param_types.Array(param_types.FLOAT64),
                             'hash': param_types.STRING, 'model': param_types.STRING}, timeout=120))
        items = {x.id: x for x in self.catalog.items}
        if not rows or any(r[0] not in items for r in rows):
            raise ValueError('Remote retrieval returned no hits or an unapproved catalog object.')
        return [{'item': asdict(items[item_id]), 'score': 1.0-float(distance)} for item_id, distance in rows]
