"""Matched four-way SQL-agent ablation: database backend x embedding retrieval.

The isolated freight copies have matching names, schema, data and semantic text.
Prepare creates a BQML vector table and copies those exact vectors to a separate
Spanner metadata table. Benchmark keeps no-embedding and native-vector paths
separate, retains failures and checks answers against independent SQL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

from google.cloud import bigquery
from google.api_core.exceptions import AlreadyExists

from graphkit.graph.agents.dataset_agent import DatasetAgent
from graphkit.graph.semantic.bqml_retrieval import BigQueryCatalogRetriever
from graphkit.graph.semantic.catalog import Catalog
from graphkit.graph.semantic.catalog import embed
from graphkit.graph.semantic.spanner_retrieval import SpannerCatalogRetriever
from graphkit.graph.core.workflow import Workspace
from benchmark_cloud import compare, stats
from cloud_questions import CASES
from validate_cloud import PROJECT, MODEL, EMBEDDING, adapter, workspace

ROOT = Path('graphkit_out/retrieval_comparison')
MODEL_REF = f'{PROJECT}.Customers_data.graphkit_catalog_embedding'


def local_workspace(backend):
    return Workspace(ROOT/backend, 'FreightGraph')


def cases():
    return list(CASES) + [
        {'id': 'alias_freight', 'question':
         'Across all consignments, return COUNT(*) AS shipment_count and ROUND(SUM(revenue),2) AS revenue.',
         'sql': 'SELECT COUNT(*) AS shipment_count, ROUND(SUM(revenue),2) AS revenue FROM {loads}'},
        {'id': 'alias_diesel', 'question':
         'Across all diesel purchases, return COUNT(*) AS purchase_count and ROUND(SUM(total_cost),2) AS fuel_cost.',
         'sql': 'SELECT COUNT(*) AS purchase_count, ROUND(SUM(total_cost),2) AS fuel_cost FROM {fuel_purchases}'}]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'benchmark'])
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('repeat must be positive')
    ROOT.mkdir(parents=True, exist_ok=True)
    sources = {backend: adapter(backend) for backend in ['bigquery', 'spanner']}
    client = sources['bigquery'].client

    if args.phase == 'prepare':
        catalogs = {}
        for backend in sources:
            old, new = workspace(backend), local_workspace(backend)
            for name in ['approved.json', 'scan.json', 'semantic.approved.json']:
                shutil.copyfile(old.dir/name, new.dir/name)
            catalogs[backend] = Catalog.load(new.dir/'semantic.approved.json')
        if catalogs['bigquery'].items != catalogs['spanner'].items:
            raise ValueError('Catalog text differs between backends.')
        catalog = catalogs['bigquery']
        table = 'GraphkitSemantic_comparison_'+catalog.fingerprint()[:12]
        ref = f'{PROJECT}.Customers_data.{table}'
        schema = [bigquery.SchemaField(n, 'STRING') for n in ['catalog_hash', 'item_id', 'content']]
        rows = [{'catalog_hash': catalog.fingerprint(), 'item_id': x.id, 'content': x.text()}
                for x in catalog.items]
        client.load_table_from_json(rows, ref+'_input', location='us-east1', job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition='WRITE_TRUNCATE')).result(timeout=120)
        sql = f'''CREATE OR REPLACE TABLE `{ref}` AS
SELECT *, '{EMBEDDING}' AS embedding_model FROM AI.GENERATE_EMBEDDING(
MODEL `{MODEL_REF}`, TABLE `{ref}_input`,
STRUCT('RETRIEVAL_DOCUMENT' AS task_type, 768 AS output_dimensionality))'''
        (ROOT/'generate.sql').write_text(sql+';\n')
        config = bigquery.QueryJobConfig(use_query_cache=False, maximum_bytes_billed=1024**3)
        client.query(sql, location='us-east1', job_config=config).result(timeout=300)
        vectors = list(client.query(f'SELECT item_id, embedding, status FROM `{ref}`',
                       location='us-east1', job_config=config).result(timeout=120))
        if len(vectors) != len(catalog.items) or any(r['status'] or len(r['embedding'] or []) != 768 for r in vectors):
            raise ValueError('Embedding failures or unexpected dimensions; inspect the vector table status.')
        by_id = {r['item_id']: list(r['embedding']) for r in vectors}
        if set(by_id) != {x.id for x in catalog.items}:
            raise ValueError('Vector identities differ from catalog.')
        for backend in sources:
            current = catalogs[backend]
            embed(current, lambda texts: [by_id[x.id] for x in current.items], EMBEDDING,
                  local_workspace(backend).dir/'embeddings.json')
        # New table avoids altering any deployed semantic catalog/version.
        ddl = (f'CREATE TABLE {table} (catalog_hash STRING(64) NOT NULL, item_id STRING(1024) NOT NULL, '
               'embedding_model STRING(MAX), embedding ARRAY<FLOAT64>) PRIMARY KEY (catalog_hash, item_id)')
        (ROOT/'spanner.sql').write_text(ddl+';\n')
        db = sources['spanner'].db
        try:
            db.update_ddl([ddl]).result(timeout=240)
        except AlreadyExists:
            pass
        sp_catalog = catalogs['spanner']
        with db.batch() as batch:
            batch.insert_or_update(table=table,
                columns=['catalog_hash', 'item_id', 'embedding_model', 'embedding'],
                values=[(sp_catalog.fingerprint(), x.id, EMBEDDING, by_id[x.id]) for x in sp_catalog.items])
        with db.snapshot() as snapshot:
            stored = list(snapshot.execute_sql(f'SELECT item_id, embedding FROM `{table}`'))
        if len(stored) != len(by_id) or any(list(v) != by_id[item_id] for item_id, v in stored):
            raise ValueError('Spanner vectors differ from BigQuery document vectors.')
        resources = {'bq_vector_table': ref, 'spanner_vector_table': table, 'model': MODEL_REF,
                     'embedding_model': EMBEDDING, 'dimensions': 768, 'objects': len(by_id),
                     'catalog_hashes': {b: c.fingerprint() for b, c in catalogs.items()}}
        (ROOT/'resources.json').write_text(json.dumps(resources, indent=2)+'\n')
        print('Prepared and verified identical document vectors on both backends:', len(by_id), flush=True)
        return

    resources = json.loads((ROOT/'resources.json').read_text())
    ws = {b: local_workspace(b) for b in sources}
    preflight = {'counts': {}, 'references': {}}
    # Fail before timing if current schemas or independent results differ.
    references = {}
    for b, source in sources.items():
        tables = ws[b].load_scan()
        preflight['counts'][b] = {}
        for table in tables:
            actual = source.describe(table.name)
            if [(c.name, c.type) for c in actual.columns] != [(c.name, c.type) for c in table.columns]:
                raise ValueError(f'Schema drift: {b}.{table.name}')
            preflight['counts'][b][table.name] = source.run_readonly(
                f'SELECT COUNT(*) AS n FROM {source.qualify(table.name)}').rows[0]['n']
        for case in cases():
            sql = case['sql'].format(**{t.name: source.qualify(t.name) for t in tables})
            started = time.perf_counter()
            references[(b, case['id'])] = source.run_readonly(sql).rows
            preflight['references'].setdefault(b, {})[case['id']] = round((time.perf_counter()-started)*1000, 2)
    if preflight['counts']['bigquery'] != preflight['counts']['spanner']:
        raise ValueError('Business row counts differ between backends.')
    for case in cases():
        if not compare(references[('bigquery', case['id'])], references[('spanner', case['id'])]):
            raise ValueError('Independent reference results differ: '+case['id'])

    from google import genai
    from google.genai import types
    model_client = genai.Client(vertexai=True, project=PROJECT, location='global',
                               http_options=types.HttpOptions(timeout=60000))
    embedding_client = genai.Client(vertexai=True, project=PROJECT, location='us-east1',
                                   http_options=types.HttpOptions(timeout=60000))
    versions, usage = set(), []

    def question_vector(question):
        response = embedding_client.models.embed_content(model=EMBEDDING, contents=question,
            config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY', output_dimensionality=768))
        return list(response.embeddings[0].values)

    def ask(prompt):
        prompt = ('Use exactly the output aliases requested. Use only the fully qualified SQL table references supplied. '
                  'Avoid reserved aliases such as at. Use portable SUM(CASE WHEN ... THEN ... ELSE ... END) '
                  'for boolean counts.\n'+prompt)
        response = model_client.models.generate_content(model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0,
                max_output_tokens=8192, thinking_config=types.ThinkingConfig(
                    thinking_level='MINIMAL' if 'Explain these executed' in prompt else 'LOW')))
        if response.model_version:
            versions.add(response.model_version)
        info = response.usage_metadata
        usage.append({'stage': 'explanation' if 'Explain these executed' in prompt else 'generation',
                      'prompt_tokens': getattr(info, 'prompt_token_count', None),
                      'output_tokens': getattr(info, 'candidates_token_count', None)})
        return json.loads(response.text)

    catalogs = {b: Catalog.load(w.dir/'semantic.approved.json') for b, w in ws.items()}
    remotes = {'bigquery': BigQueryCatalogRetriever(client, MODEL_REF, resources['bq_vector_table'], catalogs['bigquery']),
               'spanner': SpannerCatalogRetriever(sources['spanner'].db, resources['spanner_vector_table'],
                                                  catalogs['spanner'], question_vector, EMBEDDING)}
    agents = {}
    for b in sources:
        agents[b+'_no_embeddings'] = DatasetAgent(ws[b], ask, None, None, sources[b], use_embeddings=False)
        agents[b+'_native_embeddings'] = DatasetAgent(ws[b], ask, question_vector, EMBEDDING, sources[b],
                                                     retrieve_context=remotes[b])
    report = {'metadata': {'project': PROJECT, 'dataset': 'graphkit_validation',
              'spanner_instance': 'graphkit-benchmark', 'database': 'graphkit_validation',
              'spanner_capacity': 'free trial, shared 100 PU; not a production capacity test',
              'model': MODEL, 'embedding_model': EMBEDDING, 'repeat': args.repeat,
              'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'resources': resources,
              'cases': [c['id'] for c in cases()], 'paths': list(agents)},
              'preflight': preflight, 'runs': [], 'summary': {}}
    path = ROOT/'benchmark.json'
    if path.exists():
        archive = ROOT/'archive'
        archive.mkdir(exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copyfile(path, archive/f'benchmark-before-{stamp}.json')

    def save():
        report['metadata']['returned_model_versions'] = sorted(versions)
        for name in agents:
            runs = [r for r in report['runs'] if r['path'] == name]
            success = [r for r in runs if r['status'] == 'success']
            correct = [r for r in success if r.get('correct')]
            report['summary'][name] = {'requests': len(runs), 'successful': len(success), 'correct': len(correct),
                'errors': sum(r['status'] == 'error' for r in runs),
                'abstained': sum(r['status'] == 'abstained' for r in runs),
                'latency': stats([r['elapsed_ms'] for r in success]),
                'correct_latency': stats([r['elapsed_ms'] for r in correct]),
                'stages': {stage: stats([r['timings_ms'][stage] for r in success]) for stage in
                           ['retrieval', 'generation', 'execution', 'explanation']}}
        path.write_text(json.dumps(report, indent=2, default=str)+'\n')

    save()
    for i, case in enumerate(cases()):
        for repetition in range(args.repeat):
            order = list(agents)
            rotation = (i*args.repeat+repetition) % len(order)
            order = order[rotation:]+order[:rotation]
            for name in order:
                b = 'bigquery' if name.startswith('bigquery') else 'spanner'
                record = {'path': name, 'backend': b, 'id': case['id'], 'repeat': repetition,
                          'question': case['question']}
                usage.clear()
                started = time.perf_counter()
                try:
                    record.update(agents[name].answer(case['question'], mode='sql'))
                    record['correct'] = record['status'] == 'success' and compare(
                        record['rows'], references[(b, case['id'])])
                except Exception as error:
                    record.update(status='error', correct=False, error=str(error))
                record['elapsed_ms'] = round((time.perf_counter()-started)*1000, 2)
                record['model_usage'] = list(usage)
                report['runs'].append(record)
                save()
                print(json.dumps({k: record.get(k) for k in ['path', 'id', 'status', 'correct', 'elapsed_ms', 'error']}), flush=True)
    report['metadata']['finished_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    save()
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
