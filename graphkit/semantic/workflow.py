"""Explicit proposal, approval, embedding and publishing lifecycle."""
from __future__ import annotations

import json

from .catalog import Catalog, embed, load_index, propose, validate
from ..adapters import open_adapter


def table_name(spec):
    from .catalog import digest
    return 'GraphkitSemantic_' + digest(spec.name)[:16]


def semantic_ddl(spec):
    name = table_name(spec)
    if spec.backend == 'bigquery':
        loc = spec.location
        ref = f"`{loc.get('data_project') or loc['project']}.{loc['dataset']}.{name}`"
        return (f'CREATE TABLE IF NOT EXISTS {ref} (catalog_hash STRING, item_id STRING, '
                'kind STRING, table_name STRING, object_name STRING, description STRING, '
                'aliases ARRAY<STRING>, embedding_model STRING, embedding ARRAY<FLOAT64>)')
    if spec.backend == 'spanner':
        return (f'CREATE TABLE IF NOT EXISTS {name} (catalog_hash STRING(64) NOT NULL, '
                'item_id STRING(1024) NOT NULL, kind STRING(MAX), table_name STRING(MAX), '
                'object_name STRING(MAX), description STRING(MAX), aliases ARRAY<STRING(MAX)>, '
                'embedding_model STRING(MAX), embedding ARRAY<FLOAT64>) '
                'PRIMARY KEY (catalog_hash, item_id)')
    return (f'CREATE TABLE IF NOT EXISTS {name} (catalog_hash TEXT, item_id TEXT, '
            'kind TEXT, table_name TEXT, object_name TEXT, description TEXT, aliases TEXT, '
            'embedding_model TEXT, embedding TEXT, PRIMARY KEY (catalog_hash, item_id))')


def write_deployment(ws, spec):
    from ..core.terraform import BIGQUERY_TF, SPANNER_TF
    ws.tf_dir.mkdir(parents=True, exist_ok=True)
    (ws.tf_dir / 'semantic.sql').write_text(semantic_ddl(spec) + '\n')
    if spec.backend == 'sqlite':
        return
    loc = spec.location
    if spec.backend == 'bigquery':
        text = BIGQUERY_TF.format(project=loc['project'], name=table_name(spec),
            region=loc.get('region', 'US'), graph=table_name(spec))
        # The graph's main.tf owns the shared provider configuration.
        text = text.split('}\n\n', 1)[1]
    else:
        text = SPANNER_TF.format(project=loc['project'], instance=loc['instance'],
                                database=loc['database'], graph=table_name(spec))
    text = text.replace('graphkit terraform', 'graphkit semantic approve').replace('graph.sql', 'semantic.sql').replace('"property_graph"', '"semantic_catalog"')
    text = text.replace('output "graph"', 'output "semantic_catalog"')
    text = text.replace('ddl = file', 'semantic_ddl = file').replace('local.ddl', 'local.semantic_ddl')
    (ws.tf_dir / 'semantic.tf').write_text(text)


def current(ws):
    spec = ws.approved()
    if spec is None:
        raise ValueError('Confirm the graph before approving semantic metadata.')
    catalog = Catalog.load(ws.dir / 'semantic.approved.json')
    validate(catalog, spec, ws.load_scan())
    if not catalog.approved:
        raise ValueError('Semantic metadata is not approved.')
    return spec, catalog


def propose_catalog(ws, ask=None):
    spec = ws.draft()
    if spec is None:
        raise ValueError('Scan a dataset first.')
    catalog = propose(spec, ws.load_scan(), ask)
    catalog.save(ws.dir / 'semantic.draft.json')
    return catalog


def approve_catalog(ws):
    spec = ws.approved()
    if spec is None:
        raise ValueError('Confirm the graph first.')
    catalog = Catalog.load(ws.dir / 'semantic.draft.json')
    validate(catalog, spec, ws.load_scan())
    catalog.approved = True
    catalog.save(ws.dir / 'semantic.approved.json')
    write_deployment(ws, spec)
    return catalog


class GeminiEmbeddings:
    def __init__(self, model, client=None):
        from ..agents.llm import _client
        self.model, self.client = model, client or _client()

    def _embed(self, texts, task):
        from google.genai import types
        vectors = []
        for text in texts:
            response = self.client.models.embed_content(model=self.model, contents=text,
                config=types.EmbedContentConfig(task_type=task))
            vectors.append(list(response.embeddings[0].values))
        return vectors

    def documents(self, texts):
        return self._embed(texts, 'RETRIEVAL_DOCUMENT')

    def question(self, text):
        return self._embed([text], 'RETRIEVAL_QUERY')[0]


def embed_catalog(ws, embedder, model):
    _, catalog = current(ws)
    return embed(catalog, embedder, model, ws.dir / 'embeddings.json')


def publish(ws, adapter=None):
    """Publish reviewed vectors only. Run Terraform first for cloud backends.

    Rows are keyed by catalog hash + item id. Retrying is idempotent and old
    versions remain available to existing deployments.
    """
    spec, catalog = current(ws)
    index = load_index(catalog, ws.dir / 'embeddings.json')
    adapter = adapter or open_adapter(spec.backend, spec.location)
    columns = ('catalog_hash', 'item_id', 'kind', 'table_name', 'object_name',
               'description', 'aliases', 'embedding_model', 'embedding')
    rows = [(catalog.fingerprint(), item.id, item.kind, item.table, item.name,
             item.description, item.aliases, index['model'], vector)
            for item, vector in zip(catalog.items, index['vectors'])]
    name = table_name(spec)
    if spec.backend == 'sqlite':
        with adapter.conn:
            adapter.conn.execute(semantic_ddl(spec))
            adapter.conn.executemany(f'INSERT OR REPLACE INTO {name} VALUES (?,?,?,?,?,?,?,?,?)',
                [r[:6] + (json.dumps(r[6]), r[7], json.dumps(r[8])) for r in rows])
    elif spec.backend == 'spanner':
        for offset in range(0, len(rows), 100):
            with adapter.db.batch() as batch:
                batch.insert_or_update(table=name, columns=columns, values=rows[offset:offset+100])
    elif spec.backend == 'bigquery':
        from google.cloud import bigquery
        ref = adapter.qualify(name)
        # Bounded ARRAY<STRUCT> parameters avoid a separate billed job per object.
        for offset in range(0, len(rows), 25):
            records = []
            for row in rows[offset:offset+25]:
                params = []
                for col, value in zip(columns, row):
                    if col in ('aliases', 'embedding'):
                        params.append(bigquery.ArrayQueryParameter(col, 'STRING' if col == 'aliases' else 'FLOAT64', value))
                    else:
                        params.append(bigquery.ScalarQueryParameter(col, 'STRING', value))
                records.append(bigquery.StructQueryParameter(None, *params))
            items = bigquery.ArrayQueryParameter('items', 'STRUCT', records)
            fields = ', '.join(columns)
            values = ', '.join('s.' + c for c in columns)
            updates = ', '.join(f'{c} = s.{c}' for c in columns[2:])
            sql = (f'MERGE {ref} t USING UNNEST(@items) s '
                   f'ON t.catalog_hash=s.catalog_hash AND t.item_id=s.item_id '
                   f'WHEN MATCHED THEN UPDATE SET {updates} '
                   f'WHEN NOT MATCHED THEN INSERT ({fields}) VALUES ({values})')
            adapter.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=[items])).result()
    return len(rows)
