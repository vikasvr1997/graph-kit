"""Reproducible live preparation of isolated benchmark graphs and semantic catalogs."""
from __future__ import annotations
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from google import genai
from google.genai import types
from graphkit.graph.adapters import open_adapter
from graphkit.graph.core.workflow import Workspace
from graphkit.graph.core.workflow import do_scan
from graphkit.graph.core.workflow import confirm
from graphkit.graph.core.workflow import apply
from graphkit.graph.semantic.catalog import Catalog
from graphkit.graph.semantic.workflow import propose_catalog
from graphkit.graph.semantic.workflow import approve_catalog
from graphkit.graph.semantic.workflow import embed_catalog
from graphkit.graph.semantic.workflow import publish
from graphkit.graph.agents.llm import _ask

PROJECT='premium-odyssey-508202-k9'
ROOT=Path('graphkit_out/cloud_validation')
MODEL=(json.loads(Path('graphkit_out/cloud_model.json').read_text())['model']
       if Path('graphkit_out/cloud_model.json').exists() else 'gemini-3.5-flash')
EMBEDDING='gemini-embedding-001'

def workspace(backend):
    return Workspace(ROOT/backend, 'FreightGraph')

def adapter(backend):
    location=({'project':PROJECT,'dataset':'graphkit_validation','region':'us-east1',
               'use_query_cache':False} if backend=='bigquery' else
              {'project':PROJECT,'instance':'graphkit-benchmark','database':'graphkit_validation'})
    if backend=='spanner':
        from google.cloud import spanner
        from graphkit.graph.adapters.spanner import SpannerAdapter
        db=spanner.Client(project=PROJECT,disable_builtin_metrics=True).instance('graphkit-benchmark').database('graphkit_validation')
        return SpannerAdapter(location,database=db)
    return open_adapter(backend,location)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--backend',choices=['bigquery','spanner'],required=True)
    p.add_argument('--phase',choices=['scan','approve','deploy','embed','publish','verify'],required=True)
    a=p.parse_args()
    ws=workspace(a.backend)
    source=adapter(a.backend)
    if a.phase=='scan':
        spec,notes=do_scan(ws,a.backend,source.location,adapter=source,sample_rows=100,check_values=True)
        print(json.dumps({'nodes':[{'label':n.label,'table':n.table,'key':n.key} for n in spec.nodes],
                          'edges':[{'label':e.label,'table':e.table,'source':e.source,'source_key':e.source_key,
                                    'dest':e.dest,'dest_key':e.dest_key,'confidence':e.confidence} for e in spec.edges],
                          'notes':notes},indent=2),flush=True)
    elif a.phase=='approve':
        spec=ws.draft()
        assert not spec.validate()
        confirm(ws,spec)
        catalog=propose_catalog(ws)
        # Test-only vocabulary: aliases preserve real schema meanings, not extra data.
        aliases={'customers':['clients','shippers','accounts'],'drivers':['operators'],
                 'loads':['freight','consignments','shipments'],'trips':['journeys','hauls'],
                 'fuel_purchases':['diesel purchases','fuel spending'],'events':['operational events'],
                 'routes':['lanes'],'facilities':['depots','terminals']}
        for item in catalog.items:
            if item.kind=='table':
                item.aliases=aliases.get(item.table,[])
                item.description=f'Freight operations {item.table.replace("_"," ")} records.'
        catalog.save(ws.dir/'semantic.draft.json')
        approve_catalog(ws)
        print('Approved graph and test semantic vocabulary',flush=True)
    elif a.phase=='deploy':
        code,log=apply(ws,'apply')
        print(log,flush=True)
        if code:
            raise SystemExit(code)
    elif a.phase=='embed':
        client=genai.Client(vertexai=True,project=PROJECT,location='us-east1',
                            http_options=types.HttpOptions(timeout=60000))
        cache_path=ROOT/'embedding_cache.json'
        cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
        def one(text):
            if text in cache:
                return cache[text]
            result=client.models.embed_content(model=EMBEDDING,contents=text,
                config=types.EmbedContentConfig(task_type='RETRIEVAL_DOCUMENT',output_dimensionality=768))
            cache[text]=list(result.embeddings[0].values)
            return cache[text]
        def documents(texts):
            with ThreadPoolExecutor(max_workers=6) as pool:
                vectors=list(pool.map(one,texts))
            cache_path.write_text(json.dumps(cache))
            return vectors
        result=embed_catalog(ws,documents,EMBEDDING)
        print('Embedded',len(result['ids']),'catalog objects',flush=True)
    elif a.phase=='publish':
        print('Published',publish(ws,source),'semantic records',flush=True)
    else:
        from graphkit.graph.semantic.catalog import load_index
        from graphkit.graph.semantic.workflow import current
        from graphkit.graph.semantic.workflow import table_name
        spec,catalog=current(ws)
        index=load_index(catalog,ws.dir/'embeddings.json')
        query=(f'SELECT COUNT(*) AS n, COUNT(DISTINCT item_id) AS unique_ids, '
               f'SUM(CASE WHEN ARRAY_LENGTH(embedding)=768 THEN 1 ELSE 0 END) AS valid_vectors '
               f'FROM {source.qualify(table_name(spec))} '
               'WHERE catalog_hash=@hash AND embedding_model=@model')
        result=source.run(query,params={'hash':catalog.fingerprint(),'model':index['model']}).rows[0]
        assert result['n']==result['unique_ids']==result['valid_vectors']==len(catalog.items),result
        (ROOT/f'{a.backend}_semantic_verification.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result),flush=True)

if __name__=='__main__':main()
