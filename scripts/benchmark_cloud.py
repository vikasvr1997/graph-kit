"""Compare identical data, independent SQL references and complete agent requests.

Results are checkpointed after every request. BigQuery result caching is disabled.
Runs execute sequentially from the same client; this is not a load test.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import re
import statistics
import time
from numbers import Number
from pathlib import Path
from google import genai
from google.genai import types
from graphkit.graph.agents.dataset_agent import DatasetAgent
from graphkit.graph.benchmarking.generator import generate
from graphkit.graph.benchmarking.generator import normalize
from cloud_questions import CASES
from validate_cloud import PROJECT, ROOT, MODEL, EMBEDDING, adapter, workspace


def compare(actual, expected):
    if len(actual)!=len(expected): return False
    for a,e in zip(actual,expected):
        if set(a)!=set(e): return False
        for key in e:
            av,ev=a[key],e[key]
            if isinstance(av,Number) and isinstance(ev,Number):
                if not math.isclose(float(av),float(ev),abs_tol=.011,rel_tol=1e-9): return False
            elif av!=ev: return False
    return True


def stats(values):
    values=sorted(values)
    if not values:return {}
    return {'n':len(values),'p50_ms':round(statistics.median(values),2),
            'p95_ms':round(values[max(0,math.ceil(.95*len(values))-1)],2),
            'min_ms':round(values[0],2),'max_ms':round(values[-1],2)}


def summarize(runs):
    out={}
    for backend in ['bigquery','spanner']:
        subset=[r for r in runs if r['backend']==backend]
        success=[r for r in subset if r.get('status')=='success']
        out[backend]={'requests':len(subset),'successful':len(success),
                      'correct':sum(r.get('correct') is True for r in subset),
                      'errors':sum(r.get('status')=='error' for r in subset),
                      'latency':stats([r['elapsed_ms'] for r in success])}
        for stage in ['retrieval','generation','execution','explanation','total']:
            values=[r['timings_ms'][stage] for r in success if stage in r.get('timings_ms',{})]
            if values:out[backend][stage]=stats(values)
    return out


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['database','graph','agent','agent-graph','lookup'],required=True)
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--cases',type=int,default=5)
    args=parser.parse_args()
    adapters={b:adapter(b) for b in ['bigquery','spanner']}
    runs=[]
    path=ROOT/f'{args.phase}_results.json'
    references={}
    if args.phase in ('agent','agent-graph'):
        previous=json.loads((ROOT/'database_results.json').read_text())
        for r in previous['runs']:
            if r['status']=='success':references[(r['backend'],r['id'])]=r['rows']
        model_versions=set()
        clients={b:genai.Client(vertexai=True,project=PROJECT,location='global',
                               http_options=types.HttpOptions(timeout=60000)) for b in adapters}
        embedding_client=genai.Client(vertexai=True,project=PROJECT,location='us-east1',
                                     http_options=types.HttpOptions(timeout=60000))
        def embedding(question):
            result=embedding_client.models.embed_content(model=EMBEDDING,contents=question,
                config=types.EmbedContentConfig(task_type='RETRIEVAL_QUERY',output_dimensionality=768))
            return list(result.embeddings[0].values)
        def make_ask(backend):
            def ask(prompt):
                prompt=('Use exactly the output aliases requested in the question and fully qualified '
                        'SQL table references supplied in schema. Avoid reserved aliases such as at. '
                        'Use portable SUM(CASE WHEN ... THEN ... ELSE ... END) for boolean counts.\n'+prompt)
                response=clients[backend].models.generate_content(model=MODEL,contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type='application/json',temperature=0,
                        max_output_tokens=8192,
                        thinking_config=types.ThinkingConfig(thinking_level='MINIMAL' if 'Explain these executed' in prompt else 'LOW')))
                if getattr(response,'model_version',None): model_versions.add(response.model_version)
                if not response.text:raise ValueError('Model returned no text')
                parsed=json.loads(response.text)
                with (ROOT/f'{backend}_plans.jsonl').open('a') as log:
                    log.write(json.dumps(parsed,default=str)+'\n')
                return parsed
            return ask
        agents={b:DatasetAgent(workspace(b),make_ask(b),embedding,EMBEDDING,adapters[b]) for b in adapters}
    graph_queries={}
    if args.phase in ('graph','agent-graph'):
        for b in adapters:
            queries=generate(workspace(b).approved(),adapters[b],max_hops=4,limit=24)
            graph_queries[b]=[q for q in queries if q.compare=='count'][:args.cases]
        cases=[{'id':q.id,'question':q.question + ' Return one column n with the count. Use the exact graph reference provided in the schema, followed by MATCH and RETURN COUNT(*) AS n.'} for q in graph_queries['bigquery']]
    elif args.phase=='lookup':
        cases=[{'id':'trip_primary_key','question':'Fetch one trip by its primary key','table':'trips','key':'trip_id',
                'columns':'trip_id,load_id,driver_id,trip_status,actual_distance_miles'},
               {'id':'load_primary_key','question':'Fetch one load by its primary key','table':'loads','key':'load_id',
                'columns':'load_id,customer_id,route_id,revenue'},
               {'id':'customer_primary_key','question':'Fetch one customer by its primary key','table':'customers','key':'customer_id',
                'columns':'customer_id,customer_type,account_status'}][:args.cases]
        for case in cases:
            first=adapters['bigquery'].run(f"SELECT {case['key']} FROM {adapters['bigquery'].qualify(case['table'])} ORDER BY {case['key']} LIMIT 1")
            case['value']=first.rows[0][case['key']]
    else:cases=CASES[:args.cases]
    metadata={'project':PROJECT,'dataset':'graphkit_validation','instance':'graphkit-benchmark',
              'database':'graphkit_validation','region':'us-east1','client':'local macOS, America/Detroit',
              'model':MODEL,'embedding_model':EMBEDDING,'embedding_dimensions':768,
              'bigquery_result_cache':False,'query_thinking_level':'LOW','explanation_thinking_level':'MINIMAL','spanner_instance':'free trial, shared resources',
              'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'phase':args.phase,'repeat':args.repeat}
    def save():
        if args.phase in ('agent','agent-graph'): metadata['returned_model_versions']=sorted(model_versions)
        path.write_text(json.dumps({'metadata':metadata,'summary':summarize(runs),'runs':runs},indent=2,default=str))
    for index,case in enumerate(cases):
        for repeat in range(args.repeat):
            # Alternate which engine goes first to reduce ordering bias.
            order=['bigquery','spanner'] if (index+repeat)%2==0 else ['spanner','bigquery']
            pair={}
            for backend in order:
                row={'backend':backend,'id':case['id'],'repeat':repeat,'question':case['question']}
                started=time.perf_counter()
                try:
                    source=adapters[backend]
                    if args.phase in ('agent','agent-graph'):
                        answer=agents[backend].answer(case['question'],mode='gql' if args.phase=='agent-graph' else 'sql')
                        row.update(answer)
                        if args.phase=='agent-graph':
                            expected=source.run(graph_queries[backend][index].sql).rows
                        else:
                            expected=references[(backend,case['id'])]
                        row['correct']=answer.get('status')=='success' and compare(answer['rows'],expected)
                        if args.phase=='agent-graph' and answer.get('status')=='success':
                            labels=lambda query: re.findall(r'\[[^\]]*:\s*([A-Za-z][A-Za-z0-9_]*)',query)
                            required=labels(graph_queries[backend][index].gql)
                            actual=labels(answer['query'])
                            row['path_labels_match']=actual in (required,list(reversed(required)))
                            row['correct']=row['correct'] and row['path_labels_match']
                    elif args.phase=='lookup':
                        query=f"SELECT {case['columns']} FROM {source.qualify(case['table'])} WHERE {case['key']}=@key"
                        result=source.run(query,params={'key':case['value']})
                        row.update(status='success',query=query,rows=result.rows,server_ms=result.server_ms)
                        pair[backend]=result.rows
                    elif args.phase=='database':
                        refs={t:source.qualify(t) for t in ['customers','loads','trips','fuel_purchases','routes','events','drivers','facilities']}
                        query=case['sql'].format(**refs)
                        result=source.run(query)
                        row.update(status='success',query=query,rows=result.rows,server_ms=result.server_ms,
                                   bytes_processed=result.bytes_processed)
                        pair[backend]=result.rows
                    else:
                        q=graph_queries[backend][index]
                        sql=source.run(q.sql)
                        gql_started=time.perf_counter()
                        gql=source.run(q.gql)
                        row.update(status='success',query=q.gql,rows=gql.rows,
                                   correct=normalize(gql.rows,q.compare)==normalize(sql.rows,q.compare),
                                   gql_ms=(time.perf_counter()-gql_started)*1000,sql_ms=sql.elapsed_ms)
                    row['elapsed_ms']=(time.perf_counter()-started)*1000
                    if args.phase=='graph': row['elapsed_ms']=row['gql_ms']
                    elif args.phase=='agent-graph' and 'timings_ms' in row: row['elapsed_ms']=row['timings_ms']['total']
                except Exception as error:
                    row.update(status='error',error=str(error),elapsed_ms=(time.perf_counter()-started)*1000,correct=False)
                runs.append(row)
                save()
                print(json.dumps({k:v for k,v in row.items() if k in ['backend','id','repeat','status','correct','elapsed_ms','error','timings_ms']}),flush=True)
            if len(pair)==2:
                same=compare(pair['bigquery'],pair['spanner'])
                for row in runs[-2:]:row['correct']=same
                save()
    print(json.dumps(summarize(runs),indent=2),flush=True)

if __name__=='__main__':main()
