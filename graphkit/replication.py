"""Render native BigQuery-to-Spanner exports and a Google Workflows pipeline.

Control plane only: row data travels through Google's EXPORT DATA service.
A successful batch is an upsert refresh; it does not propagate hard deletes.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
TYPES = {'STRING':'STRING(MAX)', 'INTEGER':'INT64', 'INT64':'INT64',
         'FLOAT':'FLOAT64', 'FLOAT64':'FLOAT64', 'BOOLEAN':'BOOL', 'BOOL':'BOOL',
         'DATE':'DATE', 'TIMESTAMP':'TIMESTAMP', 'BYTES':'BYTES(MAX)', 'NUMERIC':'NUMERIC', 'JSON':'JSON'}


def check_config(config):
    for field in ['project_id','source_dataset','region','spanner_instance','spanner_database','workflow_name']:
        if not isinstance(config.get(field),str) or not re.fullmatch(r'[A-Za-z0-9_-]+',config[field]):
            raise ValueError(f'Invalid {field}')
    sources,targets=set(),set()
    if not config.get('tables'):
        raise ValueError('Select at least one source table.')
    for table in config['tables']:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',table['source']) or not IDENTIFIER.fullmatch(table['target']):
            raise ValueError('Invalid table identifier.')
        if table['source'] in sources or table['target'] in targets:
            raise ValueError('Duplicate source or target table.')
        sources.add(table['source']); targets.add(table['target'])
        if not table.get('key') or len(table['key']) != len(set(table['key'])) or any(not IDENTIFIER.fullmatch(k) for k in table['key']):
            raise ValueError('Explicit, unique primary-key columns are required.')
        if table['target'].lower().startswith('graphkitpipeline'):
            raise ValueError('Target name is reserved for pipeline control tables.')


def fields_for(table, schema):
    fields=schema[table['source']]['schema']
    names={f['name'] for f in fields}
    if not set(table['key']) <= names:
        raise ValueError(f"Missing primary-key columns in {table['source']}")
    for field in fields:
        if not IDENTIFIER.fullmatch(field['name']) or field['type'] not in TYPES or field.get('mode')=='REPEATED':
            raise ValueError(f"Unsupported field {table['source']}.{field['name']}; configure an explicit conversion.")
    return fields


def table_ddl(table, schema):
    fields=fields_for(table,schema)
    columns=[]
    for f in fields:
        kind=TYPES[f['type']]
        if f['name'] in table['key'] and f['type']=='STRING': kind='STRING(256)'
        nullable=f.get('mode') != 'REQUIRED' and f['name'] not in table['key']
        columns.append(f"`{f['name']}` {kind}"+('' if nullable else ' NOT NULL'))
    key=', '.join(f'`{k}`' for k in table['key'])
    return f"CREATE TABLE `{table['target']}` ("+', '.join(columns)+f') PRIMARY KEY ({key})'


def source_ref(config,table):
    return f"`{config['project_id']}.{config['source_dataset']}.{table['source']}`"


def preflight_sql(config,schema):
    checks=[]
    for table in config['tables']:
        fields=fields_for(table,schema)
        key=table['key']
        struct=', '.join(f'`{k}`' for k in key)
        invalid=' OR '.join(f'`{k}` IS NULL' for k in key)
        invalid += ''.join(f" OR CHAR_LENGTH(`{f['name']}`)>256" for f in fields if f['name'] in key and f['type']=='STRING')
        checks.append(f"ASSERT (SELECT COUNTIF({invalid})=0 AND COUNT(*)=COUNT(DISTINCT TO_JSON_STRING(STRUCT({struct}))) "
                      f"FROM {source_ref(config,table)} FOR SYSTEM_TIME AS OF @snapshot) AS '{table['source']}: invalid primary key';")
    return '\n'.join(checks)


def export_sql(config,table,schema):
    columns=', '.join('`'+f['name']+'`' for f in fields_for(table,schema))
    uri=f"https://spanner.googleapis.com/projects/{config['project_id']}/instances/{config['spanner_instance']}/databases/{config['spanner_database']}"
    options=json.dumps({'table':table['target'],'priority':'LOW','tag':'graphkit_customers_sync'})
    return (f"EXPORT DATA OPTIONS(uri='{uri}', format='CLOUD_SPANNER', spanner_options='''{options}''') "
            f'AS SELECT {columns} FROM {source_ref(config,table)} FOR SYSTEM_TIME AS OF @snapshot')


def workflow(config,schema):
    """Sequential exports with a consistent BigQuery snapshot and fail-closed lock.

    Cancellation or failure intentionally leaves the lock in place: an operator
    must verify all BigQuery jobs have stopped before removing a stale lock.
    """
    project=config['project_id']; region=config['region']; pipeline=config['workflow_name']
    database=f"projects/{project}/instances/{config['spanner_instance']}/databases/{config['spanner_database']}"
    def expr(text): return '${'+text+'}'
    def commit_step(name,mutations):
        return {name:{'call':'commit_spanner','args':{'database':database,'mutations':mutations}}}
    snapshot_param={'name':'snapshot','parameterType':{'type':'TIMESTAMP'},'parameterValue':{'value':expr('snapshot')}}
    def query_step(name,sql,suffix):
        return {name:{'call':'googleapis.bigquery.v2.jobs.insert','args':{
            'projectId':project,'body':{
                'jobReference':{'projectId':project,'location':region,'jobId':expr(f'"gk-" + run_id + "-{suffix}"')},
                'configuration':{'jobTimeoutMs':'1800000','labels':{'pipeline':'customers_to_spanner'},
                    'query':{'query':sql,'useLegacySql':False,'useQueryCache':False,'maximumBytesBilled':'1073741824',
                             'parameterMode':'NAMED','queryParameters':[snapshot_param]}}},
            'connector_params':{'timeout':2100,'polling_policy':{'initial_delay':1,'multiplier':1.5,'max_delay':15}}},
            'result':'job'}}
    def checked_query(name,sql,suffix):
        return [query_step(name,sql,suffix),
                {'check_'+name:{'switch':[{'condition':expr('map.get(job, ["status", "errorResult"]) != null'),
                   'steps':[{'fail_'+name:{'raise':expr('job.status.errorResult')}}]}]}},
                {'clear_'+name:{'assign':[{'job':None}]}}]
    steps=[{'init':{'assign':[{'run_id':expr('sys.get_env("GOOGLE_CLOUD_WORKFLOW_EXECUTION_ID")')},
                              {'snapshot':expr('time.format(sys.now())')}]}},
           commit_step('acquire_lock',[
               {'insert':{'table':'GraphkitPipelineLock','columns':['pipeline_id','run_id','started_at'],
                          'values':[[pipeline,expr('run_id'),expr('snapshot')]]}},
               {'insert':{'table':'GraphkitPipelineRuns','columns':['run_id','snapshot_at','status'],
                          'values':[[expr('run_id'),expr('snapshot'),'STARTED']]}}]),
           ]
    steps += checked_query('validate_keys',preflight_sql(config,schema),'preflight')
    for i,table in enumerate(config['tables']):
        name='export_'+table['target']
        steps += checked_query(name,export_sql(config,table,schema),str(i))
    steps += [commit_step('complete',[
        {'update':{'table':'GraphkitPipelineRuns','columns':['run_id','status','completed_at'],
                   'values':[[expr('run_id'),'SUCCEEDED',expr('time.format(sys.now())')]]}},
        {'delete':{'table':'GraphkitPipelineLock','keySet':{'keys':[[pipeline]]}}}]),
        {'done':{'return':{'run_id':expr('run_id'),'snapshot':expr('snapshot'),'status':'SUCCEEDED',
                          'source_dataset':config['source_dataset'],'tables':len(config['tables'])}}}]
    commit={'params':['database','mutations'],'steps':[
        {'create_session':{'call':'googleapis.spanner.v1.projects.instances.databases.sessions.create',
                           'args':{'database':expr('database'),'body':{}},'result':'session'}},
        {'write':{'try':{'call':'googleapis.spanner.v1.projects.instances.databases.sessions.commit',
                         'args':{'session':expr('session.name'),'body':{'singleUseTransaction':{'readWrite':{}},
                                                                   'mutations':expr('mutations')}},'result':'committed'},
                  'except':{'as':'error','steps':[
                      {'cleanup_error':{'call':'googleapis.spanner.v1.projects.instances.databases.sessions.delete',
                                        'args':{'name':expr('session.name')}}},
                      {'raise_error':{'raise':expr('error')}}]}}},
        {'cleanup':{'call':'googleapis.spanner.v1.projects.instances.databases.sessions.delete',
                    'args':{'name':expr('session.name')}}},
        {'result':{'return':expr('committed')}}]}
    return {'main':{'steps':steps},'commit_spanner':commit}


def render(config,schema,out):
    check_config(config)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    ddl=[table_ddl(t,schema) for t in config['tables']]
    ddl += ['CREATE TABLE GraphkitPipelineLock (pipeline_id STRING(128) NOT NULL, run_id STRING(128) NOT NULL, started_at TIMESTAMP NOT NULL) PRIMARY KEY (pipeline_id)',
            'CREATE TABLE GraphkitPipelineRuns (run_id STRING(128) NOT NULL, snapshot_at TIMESTAMP NOT NULL, status STRING(32) NOT NULL, completed_at TIMESTAMP) PRIMARY KEY (run_id)']
    (out/'schema.json').write_text(json.dumps(ddl,indent=2)+'\n')
    (out/'schema.sql').write_text(';\n\n'.join(ddl)+';\n')
    (out/'preflight.sql').write_text(preflight_sql(config,schema)+'\n')
    (out/'exports.sql').write_text(';\n\n'.join(export_sql(config,t,schema) for t in config['tables'])+';\n')
    (out/'workflow.json').write_text(json.dumps(workflow(config,schema),indent=2)+'\n')
    variables={k:v for k,v in config.items() if k!='tables'}
    (out/'terraform.tfvars.json').write_text(json.dumps(variables,indent=2)+'\n')
    return out
