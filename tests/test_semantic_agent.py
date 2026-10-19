import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from graphkit.agent import DatasetAgent, check_query, validate_scope
from graphkit.model import GraphSpec
from graphkit.semantic import Catalog, embed, load_index, propose, retrieve
from graphkit.semantic_workflow import (approve_catalog, embed_catalog, propose_catalog,
                                       publish, semantic_ddl, table_name)
from graphkit.workflow import Workspace, confirm


@pytest.fixture
def reviewed(tmp_path, demo):
    adapter, tables, spec = demo
    ws = Workspace(tmp_path, spec.name)
    ws.save_scan(tables)
    spec.save(ws.draft_path)
    confirm(ws, spec)
    catalog = propose_catalog(ws)
    item = next(x for x in catalog.items if x.id == 'table:suppliers')
    item.aliases = ['vendor', 'provider']
    catalog.save(ws.dir / 'semantic.draft.json')
    approve_catalog(ws)
    def vectors(texts):
        return [[1., 0.] if 'vendor' in text else [0., 1.] for text in texts]
    embed_catalog(ws, vectors, 'test-model')
    return ws, adapter


def test_approval_and_embedding_gates(tmp_path, demo):
    adapter, tables, spec = demo
    catalog = propose(spec, tables)
    with pytest.raises(ValueError, match='Approve'):
        embed(catalog, lambda texts: [[1., 0.]] * len(texts), 'test', tmp_path / 'index')
    ws = Workspace(tmp_path, spec.name)
    ws.save_scan(tables)
    spec.save(ws.draft_path)
    propose_catalog(ws)
    with pytest.raises(ValueError, match='Confirm'):
        approve_catalog(ws)
    confirm(ws, spec)
    catalog = Catalog.load(ws.dir / 'semantic.draft.json')
    catalog.items[0].name = 'invented'
    catalog.save(ws.dir / 'semantic.draft.json')
    with pytest.raises(ValueError, match='identities'):
        approve_catalog(ws)


def test_alias_retrieval_and_staleness(reviewed):
    ws, _ = reviewed
    catalog = Catalog.load(ws.dir / 'semantic.approved.json')
    index = load_index(catalog, ws.dir / 'embeddings.json')
    assert retrieve(catalog, index, [1., 0.], 1)[0]['item']['id'] == 'table:suppliers'
    catalog.items[0].description += 'changed'
    with pytest.raises(ValueError, match='stale'):
        load_index(catalog, ws.dir / 'embeddings.json')


def test_graph_change_invalidates_catalog(reviewed):
    ws, adapter = reviewed
    spec = ws.approved()
    spec.nodes[0].description = 'new business definition'
    confirm(ws, spec)
    with pytest.raises(ValueError, match='stale'):
        DatasetAgent(ws, lambda p: {}, lambda q: [1., 0.], 'test-model', adapter)


def test_publish_idempotent_and_excluded_from_scan(reviewed):
    ws, adapter = reviewed
    count = publish(ws, adapter)
    assert publish(ws, adapter) == count
    name = table_name(ws.approved())
    assert adapter.conn.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] == count
    assert name not in adapter.list_tables()


def test_agent_uses_executed_evidence_and_timings(reviewed):
    ws, adapter = reviewed
    prompts = []
    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            context = json.loads(prompt.split('\n', 1)[1])
            assert 'table:suppliers' in context['allowed_reference_ids']
            return {'mode': 'sql', 'query': 'SELECT COUNT(*) AS n FROM "suppliers"',
                    'references': ['table:suppliers'], 'interpretation': 'Number of suppliers'}
        evidence = json.loads(prompt.split('\n', 1)[1])
        return {'answer': f"There are {evidence['rows'][0]['n']} suppliers."}
    agent = DatasetAgent(ws, ask, lambda q: [1., 0.], 'test-model', adapter)
    answer = agent.answer('How many vendors?')
    assert answer['status'] == 'success'
    assert answer['rows'][0]['n'] > 0
    assert str(answer['rows'][0]['n']) in answer['answer']
    assert 'vendor' in prompts[0]
    assert answer['timings_ms']['total'] > 0
    assert answer['references'] == ['table:suppliers']


def test_agent_abstains_and_checks_model(reviewed):
    ws, adapter = reviewed
    with pytest.raises(ValueError, match='models must match'):
        DatasetAgent(ws, lambda p: {}, lambda q: [1., 0.], 'wrong-model', adapter)
    agent = DatasetAgent(ws, lambda p: {'abstain': 'Metric undefined'}, lambda q: [1., 0.], 'test-model', adapter)
    assert agent.answer('What is the optimized fulfillment score?')['status'] == 'abstained'


@pytest.mark.parametrize('query', ['DROP TABLE suppliers', 'SELECT 1; DELETE FROM suppliers',
                                    'WITH x AS (DELETE FROM suppliers RETURNING *) SELECT * FROM x'])
def test_query_rejection(query):
    with pytest.raises(ValueError):
        check_query(query, 'sql')


def test_database_prevents_writes_even_without_model_guard(reviewed):
    _, adapter = reviewed
    with pytest.raises(sqlite3.OperationalError):
        adapter.run_readonly('DELETE FROM suppliers')
    assert len(adapter.run_readonly('SELECT * FROM suppliers', max_rows=1).rows) == 2


def test_scope_checks_ctes_and_external_tables(demo):
    adapter, tables, spec = demo
    validate_scope('WITH x AS (SELECT * FROM suppliers) SELECT COUNT(*) FROM x', 'sql', spec, tables, adapter)
    for query in ['SELECT * FROM secrets', 'WITH secrets AS (SELECT * FROM hidden) SELECT * FROM secrets',
                  "SELECT * FROM read_csv('/etc/passwd')"]:
        with pytest.raises(ValueError):
            validate_scope(query, 'sql', spec, tables, adapter)


def test_catalog_includes_keyless_unrelated_tables(demo):
    from graphkit.adapters import TableInfo, Column
    _, tables, spec = demo
    tables.append(TableInfo('quality_notes', [Column('comment', 'STRING')]))
    catalog = propose(spec, tables)
    assert 'column:quality_notes.comment' in {i.id for i in catalog.items}


@pytest.mark.parametrize('backend', ['bigquery', 'spanner'])
def test_cloud_semantic_deployment(tmp_path, demo, backend):
    _, tables, spec = demo
    spec.backend = backend
    spec.location = {'project': 'p', 'dataset': 'd', 'instance': 'i', 'database': 'db'}
    ws = Workspace(tmp_path, spec.name)
    ws.save_scan(tables)
    spec.save(ws.draft_path)
    confirm(ws, spec)
    propose_catalog(ws)
    approve_catalog(ws)
    sql = (ws.tf_dir / 'semantic.sql').read_text()
    tf = (ws.tf_dir / 'semantic.tf').read_text()
    assert 'CREATE TABLE IF NOT EXISTS' in sql and 'embedding ARRAY<FLOAT64>' in sql
    assert 'semantic.sql' in tf and '"semantic_catalog"' in tf
    assert 'graph.sql' not in tf
    assert 'local.semantic_ddl' in tf and 'local.ddl' not in tf
    assert 'provider "google"' not in tf


def test_embedding_integrity(tmp_path, demo):
    _, tables, spec = demo
    catalog = propose(spec, tables)
    catalog.approved = True
    for vector in ([0., 0.], [float('nan'), 1.]):
        with pytest.raises(ValueError, match='Embeddings'):
            embed(catalog, lambda texts: [vector] * len(texts), 'test', tmp_path / 'index')


def test_bigquery_readonly_dryrun_and_limits():
    from graphkit.adapters.bigquery import BigQueryAdapter
    calls = []
    def query(sql, job_config):
        calls.append(job_config)
        if job_config.dry_run:
            return NS(statement_type='SELECT' if sql.startswith('SELECT') else 'DELETE')
        return NS(result=lambda **kw: [{'n': kw['max_results']}])
    adapter = BigQueryAdapter({'project': 'p', 'dataset': 'd'}, client=NS(query=query))
    assert adapter.run_readonly('SELECT 1', max_rows=2).rows == [{'n': 3}]
    assert calls[0].dry_run and int(calls[1].job_timeout_ms) == 30000
    with pytest.raises(ValueError):
        adapter.run_readonly('DELETE FROM d.t')
    assert len(calls) == 3


def test_cli_review_flow(tmp_path, demo, capsys):
    from graphkit.cli import main
    _, tables, spec = demo
    ws = Workspace(tmp_path, spec.name)
    ws.save_scan(tables)
    spec.save(ws.draft_path)
    assert main(['--root', str(tmp_path), 'confirm', '--name', spec.name, '--yes']) == 0
    for action in ['propose', 'approve']:
        assert main(['--root', str(tmp_path), 'semantic', action, '--name', spec.name, '--yes']) == 0
    assert (ws.dir / 'semantic.approved.json').exists()


def test_spanner_readonly_snapshot_and_cap():
    from graphkit.adapters.spanner import SpannerAdapter
    calls = []
    class Snapshot:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute_sql(self, query, **kwargs):
            calls.append(kwargs)
            class Result:
                fields = [NS(name='n')]
                def __iter__(self): return iter([[n] for n in range(10)])
            return Result()
    adapter = SpannerAdapter({}, database=NS(snapshot=Snapshot))
    assert adapter.run_readonly('SELECT 1', max_rows=2).rows == [{'n': 0}, {'n': 1}, {'n': 2}]
    assert calls == [{'timeout': 30}]


def test_cloud_publish_typed_vectors(reviewed):
    from graphkit.semantic_workflow import publish
    ws, _ = reviewed
    spec = ws.approved()
    for backend in ['bigquery', 'spanner']:
        # Reapprove against each backend to keep revision gates active.
        spec.backend = backend
        spec.location = {'project': 'p', 'dataset': 'd', 'instance': 'i', 'database': 'db'}
        confirm(ws, spec)
        propose_catalog(ws)
        approve_catalog(ws)
        embed_catalog(ws, lambda texts: [[1., 2.]] * len(texts), 'test-model')
        if backend == 'bigquery':
            calls = []
            def query(sql, job_config):
                calls.append((sql, job_config.query_parameters))
                return NS(result=lambda: [])
            adapter = NS(backend='bigquery', qualify=lambda t: '`p.d.'+t+'`', client=NS(query=query))
            count = publish(ws, adapter)
            assert len(calls) == (count + 24) // 25
            assert 'MERGE' in calls[0][0]
            assert calls[0][1][0].array_type == 'STRUCT'
            fields = calls[0][1][0].to_api_repr()['parameterType']['arrayType']['structTypes']
            assert next(f for f in fields if f['name'] == 'embedding')['type']['arrayType']['type'] == 'FLOAT64'
        else:
            rows = []
            class Batch:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def insert_or_update(self, **kwargs): rows.extend(kwargs['values'])
            count = publish(ws, NS(db=NS(batch=Batch)))
            assert len(rows) == count and rows[0][-1] == [1., 2.]


def test_agent_benchmark_tracks_failures():
    from graphkit.bench import benchmark_agent
    class Agent:
        def answer(self, q):
            if q == 'fail': raise ValueError('bad query')
            return {'status': 'abstained' if q == 'unknown' else 'success'}
    report = benchmark_agent(Agent(), ['ok', 'unknown', 'fail'], repeat=2)
    assert report['summary']['requests'] == 6
    assert report['summary']['successful'] == 2
    assert report['summary']['errors'] == 2
    assert report['summary']['abstained'] == 2
    assert report['summary']['p95_ms'] is not None


def test_bigquery_serving_result_cache_can_be_disabled():
    from graphkit.adapters.bigquery import BigQueryAdapter
    configs = []
    def query(sql, job_config):
        configs.append(job_config)
        return NS(statement_type='SELECT', result=lambda **kwargs: [])
    adapter = BigQueryAdapter({'project':'p', 'dataset':'d', 'use_query_cache':False}, client=NS(query=query))
    adapter.run_readonly('SELECT 1')
    assert configs[-1].use_query_cache is False


def test_graph_scope_requires_the_approved_graph():
    spec = GraphSpec('G', 'bigquery', {'project':'p','dataset':'d'})
    adapter = NS(graph_ref=lambda name: '`p.d.G`')
    validate_scope('GRAPH `p.d.G` MATCH (n) RETURN COUNT(*) AS n', 'gql', spec, [], adapter)
    for query in ['GRAPH MATCH (n) RETURN COUNT(*) AS n',
                  'GRAPH `p.d.Other` MATCH (n) RETURN COUNT(*) AS n',
                  'GRAPH `p.d.G` MATCH (n) RETURN n NEXT GRAPH `p.d.Other` MATCH (m) RETURN m']:
        with pytest.raises(ValueError, match='approved graph'):
            validate_scope(query, 'gql', spec, [], adapter)


def test_readonly_guard_distinguishes_load_labels_and_write_commands():
    from graphkit.adk import is_read_only_graph_query
    query = 'GRAPH G MATCH (l:Load)-[:HAS_CUSTOMER]->(c:Customer) RETURN COUNT(*) AS n'
    assert check_query(query, 'gql') == query
    assert is_read_only_graph_query(query)
    assert is_read_only_graph_query("GRAPH G MATCH (l:Load) RETURN 'LOAD; -- not a comment' AS text")
    for bad in [query + '; DELETE FROM loads', 'GRAPH G MATCH (l:Load) DELETE l',
                "GRAPH G MATCH (l:Load) RETURN l; LOAD DATA INTO x"]:
        with pytest.raises(ValueError):
            check_query(bad, 'gql')
        assert not is_read_only_graph_query(bad)
