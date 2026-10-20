import copy
import json

import pytest

from graphkit.graph.core.replication import check_config
from graphkit.graph.core.replication import export_sql
from graphkit.graph.core.replication import preflight_sql
from graphkit.graph.core.replication import render
from graphkit.graph.core.replication import workflow


@pytest.fixture
def pipeline():
    config={'project_id':'example-project','source_dataset':'Customers_data','region':'us-east1',
            'spanner_instance':'instance','spanner_database':'serving','workflow_name':'customers-sync',
            'tables':[{'source':'monthly-metrics','target':'monthly_metrics','key':['driver_id','month']}]}
    schema={'monthly-metrics':{'schema':[{'name':'driver_id','type':'STRING','mode':'NULLABLE'},
                                        {'name':'month','type':'DATE','mode':'NULLABLE'},
                                        {'name':'revenue','type':'FLOAT','mode':'NULLABLE'}]}}
    return config,schema


def test_native_export_binds_exact_source_and_snapshot(pipeline):
    config,schema=pipeline
    sql=export_sql(config,config['tables'][0],schema)
    assert '`example-project.Customers_data.monthly-metrics`' in sql
    assert 'FOR SYSTEM_TIME AS OF @snapshot' in sql
    assert "format='CLOUD_SPANNER'" in sql and '"priority": "LOW"' in sql
    assert 'INSERT INTO' not in sql and 'CREATE TABLE' not in sql


def test_preflight_rejects_nulls_and_duplicate_composite_keys(pipeline):
    config,schema=pipeline
    sql=preflight_sql(config,schema)
    assert '`driver_id` IS NULL OR `month` IS NULL' in sql
    assert 'COUNT(DISTINCT TO_JSON_STRING(STRUCT(`driver_id`, `month`)))' in sql
    assert 'CHAR_LENGTH(`driver_id`)>256' in sql


def test_workflow_serializes_validated_exports_and_releases_only_on_success(pipeline):
    config,schema=pipeline
    flow=workflow(config,schema)
    names=[next(iter(s)) for s in flow['main']['steps']]
    assert names.index('acquire_lock')<names.index('validate_keys')<names.index('export_monthly_metrics')<names.index('complete')
    assert 'check_validate_keys' in names and 'check_export_monthly_metrics' in names
    query=next(s['export_monthly_metrics'] for s in flow['main']['steps'] if 'export_monthly_metrics' in s)
    assert query['args']['body']['configuration']['query']['queryParameters'][0]['parameterValue']['value']=='${snapshot}'
    assert query['args']['connector_params']['timeout']==2100
    serialized=json.dumps(flow)
    assert serialized.count('GraphkitPipelineLock')==2  # one acquire, one final release
    write=flow['commit_spanner']['steps'][1]['write']['try']
    assert write['args']['session']=='${session.name}'
    assert 'singleUseTransaction' in write['args']['body']

    config['tables'].append({'source':'extra','target':'extra','key':['driver_id','month']})
    schema['extra']=schema['monthly-metrics']
    flow=workflow(config,schema)
    names=[]
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='steps':
                    names.extend(next(iter(step)) for step in item)
                collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(flow['main'])
    assert len(names)==len(set(names)), 'Workflows step names must be unique within each subworkflow'


def test_render_preserves_composite_key_types(pipeline,tmp_path):
    config,schema=pipeline
    render(config,schema,tmp_path)
    ddl=json.loads((tmp_path/'schema.json').read_text())[0]
    assert '`driver_id` STRING(256) NOT NULL' in ddl
    assert '`month` DATE NOT NULL' in ddl
    assert 'PRIMARY KEY (`driver_id`, `month`)' in ddl
    assert json.loads((tmp_path/'workflow.json').read_text())['main']


def test_invalid_mapping_and_unsupported_types_fail_before_export(pipeline,tmp_path):
    config,schema=pipeline
    config['tables'].append(copy.deepcopy(config['tables'][0]))
    with pytest.raises(ValueError,match='Duplicate'):check_config(config)
    config['tables'].pop()
    schema['monthly-metrics']['schema'][2]['type']='STRUCT'
    with pytest.raises(ValueError,match='Unsupported'):render(config,schema,tmp_path)
    assert not (tmp_path/'workflow.json').exists()
