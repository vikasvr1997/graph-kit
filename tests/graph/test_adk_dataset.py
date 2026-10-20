import json

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from graphkit.graph.agents.adk_dataset import AdkDatasetAgent, make_cloud_toolset
from graphkit.graph.core.workflow import Workspace, confirm
from graphkit.graph.semantic.workflow import propose_catalog, approve_catalog


class FakeModel(BaseLlm):
    response: dict = Field(default_factory=dict)
    prompts: list = Field(default_factory=list)

    async def generate_content_async(self, llm_request, stream=False):
        self.prompts.append(llm_request)
        yield LlmResponse(content=types.Content(role='model', parts=[types.Part(text=json.dumps(self.response))]))


@pytest.fixture
def dataset(tmp_path, demo):
    adapter, tables, spec = demo
    ws = Workspace(tmp_path, spec.name)
    ws.save_scan(tables)
    spec.save(ws.draft_path)
    confirm(ws, spec)
    propose_catalog(ws)
    approve_catalog(ws)
    return ws, adapter


def build(dataset, plan, **kwargs):
    ws, adapter = dataset
    planner = FakeModel(model='fake-planner', response=plan)
    explainer = FakeModel(model='fake-explainer', response={'answer': 'There are eight suppliers.'})
    return AdkDatasetAgent(ws, adapter=adapter, use_embeddings=False,
                           planner_model=planner, explanation_model=explainer, **kwargs), planner, explainer


PLAN = {'mode': 'sql', 'query': 'SELECT COUNT(*) AS n FROM "suppliers"',
        'references': ['table:suppliers'], 'interpretation': 'Supplier count'}


def test_adk_workflow_executes_and_explains_evidence(dataset):
    agent, planner, explainer = build(dataset, PLAN)
    result = agent.answer('How many suppliers?')
    assert result['engine'] == 'adk'
    assert result['rows'] == [{'n': 8}]
    assert result['references'] == ['table:suppliers']
    assert result['answer'] == 'There are eight suppliers.'
    assert result['timings_ms']['total'] >= 0
    assert len(planner.prompts) == len(explainer.prompts) == 1


@pytest.mark.parametrize('change,match', [
    ({'query': 'DELETE FROM suppliers'}, 'read-only'),
    ({'query': 'SELECT * FROM unauthorized_table'}, 'outside'),
    ({'references': ['invented']}, 'cite existing'),
])
def test_adk_rejects_invalid_plans_before_execution(dataset, change, match, monkeypatch):
    agent, _, explainer = build(dataset, {**PLAN, **change})
    monkeypatch.setattr(dataset[1], 'run_readonly', lambda *a, **k: pytest.fail('Must not execute'))
    with pytest.raises(ValueError, match=match):
        agent.answer('Count suppliers')
    assert not explainer.prompts


def test_adk_abstention_skips_database_and_explanation(dataset, monkeypatch):
    agent, _, explainer = build(dataset, {'abstain': 'Unsupported business definition'})
    monkeypatch.setattr(dataset[1], 'run_readonly', lambda *a, **k: pytest.fail('Must not execute'))
    result = agent.answer('Unknown metric')
    assert result['status'] == 'abstained'
    assert not explainer.prompts


def test_native_toolsets_are_readonly_and_limited():
    from google.auth.credentials import AnonymousCredentials
    from google.adk.integrations.bigquery.config import WriteMode
    from google.adk.tools.spanner.settings import Capabilities, QueryResultMode
    bq = make_cloud_toolset('bigquery', {'project': 'test'}, 10, AnonymousCredentials())
    sp = make_cloud_toolset('spanner', {'project': 'test'}, 10, AnonymousCredentials())
    assert bq._tool_settings.write_mode == WriteMode.BLOCKED
    assert bq._tool_settings.maximum_bytes_billed == 10**9
    assert bq._tool_settings.max_query_result_rows == 11
    assert sp._tool_settings.capabilities == [Capabilities.DATA_READ]
    assert sp._tool_settings.query_result_mode == QueryResultMode.DICT_LIST


def test_matches_legacy_evidence_on_same_plan(dataset):
    from graphkit.graph.agents.dataset_agent import DatasetAgent
    ws, adapter = dataset
    def ask(prompt):
        return {'answer': 'There are eight suppliers.'} if prompt.startswith('Explain') else PLAN
    baseline = DatasetAgent(ws, ask, None, None, adapter, use_embeddings=False).answer('Count suppliers')
    agent, _, _ = build(dataset, PLAN)
    actual = agent.answer('Count suppliers')
    for key in ['status', 'query', 'mode', 'rows', 'references', 'truncated', 'catalog_revision', 'answer']:
        assert actual[key] == baseline[key]


def test_native_cloud_execution_uses_fixed_workspace_target(dataset):
    import asyncio
    calls = []
    class Tool:
        name = 'execute_sql'
        async def run_async(self, *, args, tool_context):
            calls.append(args)
            return {'status': 'SUCCESS', 'rows': [{'n': 8}], 'result_is_likely_truncated': False}
    class Toolset:
        async def get_tools(self):
            return [Tool()]
        async def close(self):
            calls.append('closed')
    agent, _, _ = build(dataset, PLAN, toolset_factory=lambda *a: Toolset())
    agent.dataset.spec.backend = 'spanner'
    agent.dataset.spec.location = {'project': 'approved-project', 'instance': 'approved-instance',
                                   'database': 'approved-database'}
    result = asyncio.run(agent.answer_async('Count suppliers'))
    assert result['rows'] == [{'n': 8}]
    assert calls[0] == {'project_id': 'approved-project', 'instance_id': 'approved-instance',
                        'database_id': 'approved-database', 'query': PLAN['query']}
    assert calls[-1] == 'closed'


def test_api_awaits_adk_workflow(dataset, monkeypatch):
    from fastapi.testclient import TestClient
    from graphkit.graph.api import app
    from graphkit.graph.agents import runtime
    agent, _, _ = build(dataset, PLAN)
    monkeypatch.setattr(runtime, 'create_dataset_agent', lambda *a, **k: agent)
    response = TestClient(app).post('/api/semantic/ask', json={
        'name': 'test', 'question': 'Count suppliers', 'use_embeddings': False,
    })
    assert response.status_code == 200
    assert response.json()['engine'] == 'adk'
    assert response.json()['rows'] == [{'n': 8}]


def test_model_generation_is_bounded():
    from graphkit.graph.agents.adk_dataset import generation_config
    config = generation_config('gemini-3.5-flash', 2048)
    assert config.max_output_tokens == 2048
    assert config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert generation_config('gemini-2.5-flash', 4096).thinking_config is None


def test_configured_generation_default_is_used_at_api_startup():
    import os, subprocess, sys
    code = """
from graphkit.graph.api import SemanticAskBody
from graphkit.shared.models import DEFAULTS
assert DEFAULTS['generation_model'] == 'gemini-2.5-flash'
assert SemanticAskBody(name='demo', question='Count suppliers').generation_model == 'gemini-2.5-flash'
"""
    result = subprocess.run([sys.executable, '-c', code],
        env={**os.environ, 'GRAPHKIT_MODEL': 'gemini-2.5-flash', 'CHAT_ENABLED': 'false'},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
