"""Native BigQuery ML question embeddings and version-pinned catalog retrieval."""
from __future__ import annotations

import re
from dataclasses import asdict


def qualified(ref):
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+', ref):
        raise ValueError('Expected a project.dataset.object reference.')
    return f'`{ref}`'


class BigQueryCatalogRetriever:
    """One BigQuery job per question: model inference plus exact cosine search.

    The table must contain a single catalog version with successful embeddings
    generated using the same model and dimensions as the question. Exact search
    is intentional for small schema catalogs; this does not require an ANN index.
    """
    def __init__(self, client, model_ref, table_ref, catalog, *, dimensions=768):
        self.client, self.catalog = client, catalog
        self.model, self.table = qualified(model_ref), qualified(table_ref)
        if not catalog.approved or not isinstance(dimensions, int) or dimensions < 1:
            raise ValueError('An approved catalog and positive dimensions are required.')
        self.dimensions = dimensions

    def __call__(self, question, top_k=8):
        from google.cloud import bigquery

        if not isinstance(top_k, int) or top_k < 1 or not self.catalog.items:
            raise ValueError('Invalid retrieval limit.')
        top_k = min(top_k, len(self.catalog.items))
        sql = f"""SELECT base.item_id, base.catalog_hash, distance
FROM VECTOR_SEARCH(
  TABLE {self.table}, 'embedding',
  (SELECT embedding FROM AI.GENERATE_EMBEDDING(
     MODEL {self.model}, (SELECT @question AS content),
     STRUCT('RETRIEVAL_QUERY' AS task_type,
            {self.dimensions} AS output_dimensionality)) WHERE status = ''),
  top_k => {top_k}, distance_type => 'COSINE',
  options => '{{"use_brute_force":true}}')
ORDER BY distance, base.item_id"""
        config = bigquery.QueryJobConfig(
            use_query_cache=False, maximum_bytes_billed=1024**3,
            query_parameters=[bigquery.ScalarQueryParameter('question', 'STRING', question)],
            labels={'purpose': 'graphkit_bqml_retrieval'})
        rows = list(self.client.query(sql, job_config=config).result(timeout=180))
        if not rows:
            raise ValueError('No catalog hits; check question embedding status and catalog contents.')
        items = {x.id: x for x in self.catalog.items}
        if any(r['catalog_hash'] != self.catalog.fingerprint() or r['item_id'] not in items for r in rows):
            raise ValueError('Remote search returned a different catalog version or unknown object.')
        return [{'item': asdict(items[r['item_id']]), 'score': 1.0-float(r['distance'])} for r in rows]
