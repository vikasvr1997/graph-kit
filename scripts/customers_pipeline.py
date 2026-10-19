"""Render, run and verify the native Customers_data reverse-ETL workflow.

No table rows are uploaded by this tool. BigQuery EXPORT DATA performs the copy.
Verification reads only aggregates and five sample rows per table; samples are
compared in memory and never written to reports or logs.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from numbers import Number

ROOT=Path('pipelines/customers_to_spanner')
PRIVATE=Path('graphkit_out/customers_pipeline')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['render','run','verify'])
    parser.add_argument('--config',default=str(ROOT/'config.json'))
    parser.add_argument('--execution',help='Workflow execution ID for verification')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    from google.cloud import bigquery
    bq=bigquery.Client(project=config['project_id'],location=config['region'])
    PRIVATE.mkdir(parents=True,exist_ok=True)
    if args.action=='render':
        from graphkit.replication import render
        def describe(table):
            actual=bq.get_table(f"{config['project_id']}.{config['source_dataset']}.{table['source']}")
            if actual.table_type!='TABLE':raise ValueError('Only base tables support this snapshot pipeline.')
            return table['source'],{'schema':[{'name':f.name,'type':f.field_type,'mode':f.mode} for f in actual.schema]}
        with ThreadPoolExecutor(max_workers=6) as pool:
            schema=dict(pool.map(describe,config['tables']))
        out=ROOT/'generated'
        render(config,schema,out)
        (out/'source_schema.json').write_text(json.dumps(schema,indent=2)+'\n')
        print('Rendered native exports and schema for',len(schema),'tables',flush=True)
        return
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
    http=AuthorizedSession(credentials)
    base=f"https://workflowexecutions.googleapis.com/v1/projects/{config['project_id']}/locations/{config['region']}/workflows/{config['workflow_name']}/executions"
    if args.action=='run':
        response=http.post(base,json={},timeout=30);response.raise_for_status()
        execution=response.json()
        (PRIVATE/'last_execution.json').write_text(json.dumps(execution,indent=2))
        print('Started',execution['name'],flush=True)
        while execution['state'] in ('ACTIVE','QUEUED'):
            time.sleep(10)
            response=http.get('https://workflowexecutions.googleapis.com/v1/'+execution['name'],timeout=30)
            response.raise_for_status();execution=response.json()
            (PRIVATE/'last_execution.json').write_text(json.dumps(execution,indent=2))
            print('Workflow state:',execution['state'],flush=True)
        if execution['state']!='SUCCEEDED':
            print(json.dumps(execution.get('error',{}),indent=2),flush=True)
            raise SystemExit(1)
        print(execution['result'],flush=True)
        return
    if args.execution:
        response=http.get(base+'/'+args.execution,timeout=30);response.raise_for_status()
        execution=response.json()
    else:
        execution=json.loads((PRIVATE/'last_execution.json').read_text())
    if execution['state']!='SUCCEEDED':raise ValueError('Verify only after successful workflow completion.')
    completed=json.loads(execution['result'])
    snapshot=completed['snapshot']
    from google.cloud import spanner
    db=spanner.Client(project=config['project_id'],disable_builtin_metrics=True).instance(config['spanner_instance']).database(config['spanner_database'])
    schema=json.loads((ROOT/'generated/source_schema.json').read_text())
    from graphkit.replication import source_ref
    def source_query(sql):
        cfg=bigquery.QueryJobConfig(use_query_cache=False,maximum_bytes_billed=1024**3,
            query_parameters=[bigquery.ScalarQueryParameter('snapshot','TIMESTAMP',snapshot)])
        return [dict(r) for r in bq.query(sql,job_config=cfg).result(timeout=120)]
    def target_query(sql):
        with db.snapshot() as snap:
            result=snap.execute_sql(sql,timeout=120)
            values=list(result);names=[f.name for f in result.fields]
        return [dict(zip(names,row)) for row in values]
    def equal(a,b):
        if isinstance(a,Number) and isinstance(b,Number):
            return math.isclose(float(a),float(b),rel_tol=1e-9,abs_tol=.01)
        if isinstance(a,dt.datetime) and isinstance(b,dt.datetime):return a==b
        return a==b
    results=[]
    for table in config['tables']:
        fields=schema[table['source']]['schema']
        expressions=['COUNT(*) AS row_count']
        for i,field in enumerate(fields):
            col='`'+field['name']+'`'
            expressions.append(f'SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS nulls_{i}')
            if field['type'] in ('INTEGER','INT64','FLOAT','FLOAT64','NUMERIC'):
                expressions.append(f'SUM(COALESCE({col},0)) AS total_{i}')
            elif field['type']=='STRING':
                expressions.append(f'SUM(COALESCE(CHAR_LENGTH({col}),0)) AS length_{i}')
        select='SELECT '+', '.join(expressions)+' FROM '
        expected=source_query(select+source_ref(config,table)+' FOR SYSTEM_TIME AS OF @snapshot')[0]
        actual=target_query(select+'`'+table['target']+'`')[0]
        aggregates=all(equal(expected[k],actual[k]) for k in expected)
        order=', '.join('`'+k+'`' for k in table['key'])
        a=source_query('SELECT * FROM '+source_ref(config,table)+' FOR SYSTEM_TIME AS OF @snapshot ORDER BY '+order+' LIMIT 5')
        b=target_query('SELECT * FROM `'+table['target']+'` ORDER BY '+order+' LIMIT 5')
        samples=len(a)==len(b) and all(set(x)==set(y) and all(equal(x[k],y[k]) for k in x) for x,y in zip(a,b))
        result={'source':table['source'],'target':table['target'],'source_rows':expected['row_count'],
                'target_rows':actual['row_count'],'aggregates_match':aggregates,'sample_rows_match':samples}
        results.append(result);print(json.dumps(result),flush=True)
    report={'execution':execution['name'],'snapshot':snapshot,'tables':results,
            'all_passed':all(r['aggregates_match'] and r['sample_rows_match'] for r in results)}
    (PRIVATE/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['all_passed']:raise SystemExit(1)
    print('Verified',len(results),'tables and',sum(r['source_rows'] for r in results),'rows',flush=True)

if __name__=='__main__':main()
