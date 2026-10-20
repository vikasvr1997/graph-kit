"""Schema-only BQML setup and live agent correctness/latency evaluation.

Run prepare, then embed, then benchmark. Business rows are read only for query
execution; only schema metadata is sent to the embedding model. Detailed agent
results stay in ignored graphkit_out. SQL is saved there for inspection.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from graphkit.graph.adapters.bigquery import BigQueryAdapter
from graphkit.graph.agents.dataset_agent import DatasetAgent
from graphkit.graph.semantic.bqml_retrieval import BigQueryCatalogRetriever
from graphkit.graph.core.model import GraphSpec
from graphkit.graph.semantic.catalog import Catalog
from graphkit.graph.semantic.catalog import embed
from graphkit.graph.semantic.catalog import propose
from graphkit.graph.semantic.catalog import retrieve
from graphkit.graph.core.workflow import Workspace
from graphkit.graph.core.workflow import confirm
from benchmark_cloud import compare, stats
from cloud_questions import CASES
from validate_cloud import MODEL

PROJECT = 'premium-odyssey-508202-k9'
DATASET = 'Customers_data'
REGION = 'us-east1'
EMBEDDING = 'gemini-embedding-001'
MODEL_REF = f'{PROJECT}.{DATASET}.graphkit_catalog_embedding'
CONNECTION = f'{PROJECT}.{REGION}.graphkit-schema-embeddings'
ROOT = Path('graphkit_out/bqml_customers')
WS = Workspace(ROOT, 'CustomersBqmlTest')
LOCATION = {'project': PROJECT, 'dataset': DATASET, 'region': REGION, 'use_query_cache': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'embed', 'benchmark'])
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    client = bigquery.Client(project=PROJECT, location=REGION)
    adapter = BigQueryAdapter(LOCATION, client=client)
    jobs = []

    def query(sql, params=None):
        job = client.query(sql, job_config=bigquery.QueryJobConfig(
            use_query_cache=False, maximum_bytes_billed=1024**3,
            query_parameters=params or [], labels={'purpose': 'graphkit_bqml_test'}))
        jobs.append(job.job_id)
        return list(job.result(timeout=300))

    if args.phase == 'prepare':
        config = json.loads(Path('pipelines/customers_to_spanner/config.json').read_text())
        # Explicit business-table allowlist excludes pipeline/catalog control tables.
        tables = [adapter.describe(t['source']) for t in config['tables']]
        WS.save_scan(tables)
        # Reuse the previously reviewed freight graph mappings, translating only
        # physical names to the original source dataset. Do not deploy a graph.
        spec = GraphSpec.load('graphkit_out/cloud_validation/bigquery/FreightGraph/approved.json')
        mapping = {'customers': 'customer_data', 'events': 'daily-events'}
        spec.name, spec.location = WS.name, LOCATION
        by_table = {t.name: t for t in tables}
        for node in spec.nodes:
            node.table = mapping.get(node.table, node.table)
            assert set(node.key) <= {c.name for c in by_table[node.table].columns}
        for edge in spec.edges:
            edge.table = mapping.get(edge.table, edge.table)
            assert set(edge.key+edge.source_key+edge.dest_key) <= {c.name for c in by_table[edge.table].columns}
        spec.save(WS.draft_path)
        confirm(WS, spec)  # test scope: reused mappings; Terraform is not applied
        spec = WS.approved()
        catalog = propose(spec, tables)
        aliases = {'customer_data': ['customers', 'clients', 'shippers', 'accounts'],
                   'loads': ['freight', 'consignments', 'shipments'], 'drivers': ['operators'],
                   'trips': ['journeys', 'hauls'], 'routes': ['lanes'],
                   'daily-events': ['events', 'operational events'],
                   'fuel_purchases': ['diesel purchases', 'fuel spending'],
                   'facilities': ['depots', 'terminals']}
        for item in catalog.items:
            if item.kind == 'table':
                item.description = f'Freight operations {item.table.replace("_", " ").replace("-", " ")} records.'
                item.aliases = aliases.get(item.table, [])
            elif item.kind == 'column':
                item.aliases = [item.name.replace('_', ' ')]
        # No AI-invented definitions: existing reviewed aliases and literal names.
        catalog.approved = True
        catalog.save(WS.dir/'semantic.approved.json')
        catalog.save(WS.dir/'semantic.draft.json')
        ref = f'{PROJECT}.{DATASET}.GraphkitSemantic_bqml_{catalog.fingerprint()[:12]}'
        schema = [bigquery.SchemaField(n, 'STRING') for n in
                  ['catalog_hash', 'item_id', 'kind', 'table_name', 'object_name', 'description', 'content']]
        schema += [bigquery.SchemaField('aliases', 'STRING', mode='REPEATED')]
        rows = [{'catalog_hash': catalog.fingerprint(), 'item_id': x.id, 'kind': x.kind,
                 'table_name': x.table, 'object_name': x.name, 'description': x.description,
                 'aliases': x.aliases, 'content': x.text()} for x in catalog.items]
        client.load_table_from_json(rows, ref+'_input', job_config=bigquery.LoadJobConfig(
            schema=schema, write_disposition='WRITE_TRUNCATE')).result(timeout=120)
        sql = f"CREATE MODEL `{MODEL_REF}` REMOTE WITH CONNECTION `{CONNECTION}` OPTIONS(endpoint='{EMBEDDING}')"
        (ROOT/'model.sql').write_text(sql+';\n')
        try:
            model = client.get_model(MODEL_REF)
            # Refuse to silently replace an unrelated model.
            remote = model._properties.get('remoteModelInfo', {})
            if EMBEDDING not in remote.get('endpoint', ''):
                raise ValueError('Existing model endpoint differs; inspect it before replacement.')
        except NotFound:
            query(sql)
        (ROOT/'resources.json').write_text(json.dumps({'table': ref, 'model': MODEL_REF,
            'embedding_model': EMBEDDING, 'dimensions': 768, 'objects': len(rows),
            'source_tables': len(tables), 'catalog_hash': catalog.fingerprint()}, indent=2)+'\n')
        print(f'Prepared {len(rows)} catalog objects from {len(tables)} source tables; model {MODEL_REF}', flush=True)
        return

    resources = json.loads((ROOT/'resources.json').read_text())
    ref = resources['table']
    catalog = Catalog.load(WS.dir/'semantic.approved.json')
    if args.phase == 'embed':
        started = time.perf_counter()
        sql = f"""CREATE OR REPLACE TABLE `{ref}` AS
SELECT *, '{EMBEDDING}' AS embedding_model FROM AI.GENERATE_EMBEDDING(
MODEL `{MODEL_REF}`, TABLE `{ref}_input`,
STRUCT('RETRIEVAL_DOCUMENT' AS task_type, 768 AS output_dimensionality))"""
        (ROOT/'embed.sql').write_text(sql+';\n')
        query(sql)
        rows = query(f'SELECT item_id, embedding, status, statistics FROM `{ref}`')
        failed = [r['item_id'] for r in rows if r['status'] or len(r['embedding'] or []) != 768]
        if failed:
            (ROOT/'embedding_failures.json').write_text(json.dumps(
                [{'item_id': r['item_id'], 'status': r['status']} for r in rows if r['status']], indent=2))
            raise ValueError(f'{len(failed)} embeddings failed; inspect status before publishing.')
        by_id = {r['item_id']: list(r['embedding']) for r in rows}
        if set(by_id) != {x.id for x in catalog.items} or len(rows) != len(by_id):
            raise ValueError('Embedding identities are missing or duplicated.')
        embed(catalog, lambda texts: [by_id[x.id] for x in catalog.items], EMBEDDING, WS.dir/'embeddings.json')
        resources.update(generation_ms=round((time.perf_counter()-started)*1000, 2), jobs=jobs,
                         successful_embeddings=len(rows))
        (ROOT/'resources.json').write_text(json.dumps(resources, indent=2)+'\n')
        print(f'Generated and verified {len(rows)} embeddings, 768 dimensions; saved to {ref}', flush=True)
        return

    from google import genai
    from google.genai import types
    model_client = genai.Client(vertexai=True, project=PROJECT, location='global',
                               http_options=types.HttpOptions(timeout=60000))
    embedding_client = genai.Client(vertexai=True, project=PROJECT, location=REGION,
                                   http_options=types.HttpOptions(timeout=60000))
    versions = set()

    def question_vector(question):
        response = embedding_client.models.embed_content(model=EMBEDDING, contents=question,
            config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY', output_dimensionality=768))
        return list(response.embeddings[0].values)

    def ask(prompt):
        prompt = ('Use exactly the output aliases requested. Use only fully qualified SQL table references. '
                  'Avoid reserved aliases such as at.\n'+prompt)
        response = model_client.models.generate_content(model=MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0,
                max_output_tokens=8192, thinking_config=types.ThinkingConfig(
                    thinking_level='MINIMAL' if 'Explain these executed' in prompt else 'LOW')))
        if response.model_version:
            versions.add(response.model_version)
        return json.loads(response.text)

    remote = BigQueryCatalogRetriever(client, MODEL_REF, ref, catalog)
    agents = {'bigquery_vector': DatasetAgent(WS, ask, question_vector, EMBEDDING, adapter,
                                             retrieve_context=remote),
              'local_vector': DatasetAgent(WS, ask, question_vector, EMBEDDING, adapter)}
    index = agents['local_vector'].index
    probes = [('Which shippers have consignments?', 'customer_data'),
              ('Show operators and their journeys', 'drivers'),
              ('What are diesel purchases?', 'fuel_purchases'),
              ('Show operational events at depots', 'daily-events')]
    results = {'resources': resources, 'generation_model': MODEL, 'repeat': args.repeat,
               'cache': False, 'retrieval_probes': [], 'runs': [], 'summary': {}}
    path = ROOT/'benchmark.json'

    def save():
        results['returned_model_versions'] = sorted(versions)
        for name in agents:
            runs = [r for r in results['runs'] if r['path'] == name]
            success = [r for r in runs if r['status'] == 'success']
            results['summary'][name] = {'requests': len(runs), 'successful': len(success),
                'correct': sum(r.get('correct') is True for r in runs),
                'latency': stats([r['elapsed_ms'] for r in success]),
                'correct_latency': stats([r['elapsed_ms'] for r in success if r.get('correct')]),
                'stages': {stage: stats([r['timings_ms'][stage] for r in success])
                           for stage in ['retrieval', 'generation', 'execution', 'explanation']}}
        path.write_text(json.dumps(results, indent=2, default=str)+'\n')

    for question, expected in probes:
        for name in agents:
            started = time.perf_counter()
            try:
                hits = (remote(question, 8) if name == 'bigquery_vector' else
                        retrieve(catalog, index, question_vector(question), 8))
                result = {'path': name, 'question': question, 'expected_table': expected,
                          'elapsed_ms': round((time.perf_counter()-started)*1000, 2),
                          'ids': [h['item']['id'] for h in hits],
                          'expected_table_in_top8': any(h['item']['table'] == expected for h in hits)}
            except Exception as error:
                result = {'path': name, 'question': question, 'status': 'error', 'error': str(error)}
            results['retrieval_probes'].append(result)
            save()
            print(json.dumps(result), flush=True)

    logical = {t['target']: t['source'] for t in json.loads(
        Path('pipelines/customers_to_spanner/config.json').read_text())['tables']}
    cases = list(CASES)
    # Short, alias-heavy questions supplement the explicitly specified complex cases.
    cases += [{'id': 'alias_freight', 'question':
               'Across all consignments, return COUNT(*) AS shipment_count and ROUND(SUM(revenue),2) AS revenue.',
               'sql': 'SELECT COUNT(*) AS shipment_count, ROUND(SUM(revenue),2) AS revenue FROM {loads}'},
              {'id': 'alias_diesel', 'question':
               'Across all diesel purchases, return COUNT(*) AS purchase_count and ROUND(SUM(total_cost),2) AS fuel_cost.',
               'sql': 'SELECT COUNT(*) AS purchase_count, ROUND(SUM(total_cost),2) AS fuel_cost FROM {fuel_purchases}'}]
    for i, case in enumerate(cases):
        expected = adapter.run_readonly(case['sql'].format(**{
            name: adapter.qualify(source) for name, source in logical.items()})).rows
        for repetition in range(args.repeat):
            order = list(agents) if (i+repetition) % 2 == 0 else list(reversed(agents))
            for name in order:
                record = {'path': name, 'id': case['id'], 'repeat': repetition, 'question': case['question']}
                started = time.perf_counter()
                try:
                    answer = agents[name].answer(case['question'], mode='sql')
                    record.update(answer)
                    record['correct'] = answer.get('status') == 'success' and compare(answer['rows'], expected)
                except Exception as error:
                    record.update(status='error', error=str(error), correct=False)
                record['elapsed_ms'] = round((time.perf_counter()-started)*1000, 2)
                results['runs'].append(record)
                save()
                print(json.dumps({k: record.get(k) for k in ['path', 'id', 'status', 'correct', 'elapsed_ms', 'error']}), flush=True)
    print(json.dumps(results['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
