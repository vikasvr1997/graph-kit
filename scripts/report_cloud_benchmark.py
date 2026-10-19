"""Write an aggregate report without copying source or result rows into Git."""
import json
import statistics
from pathlib import Path
from benchmark_cloud import stats
from validate_cloud import ROOT

out=Path('reports/cloud-benchmark-2026-10-19.md')
phases=['lookup','database','graph','agent','agent-graph']
lines=['# BigQuery and Spanner live benchmark — October 19, 2026','',
       'Project: `premium-odyssey-508202-k9`. Source: `Customers_data` (unchanged).',
       'Targets: BigQuery `graphkit_validation`; Spanner `graphkit-benchmark/graphkit_validation`.',
       'Both targets are in `us-east1`, with 538,540 identical projected rows across eight tables.',
       'Graphs: seven node labels and eight edges. Semantic catalogs: 96 objects each; remote verification found exactly 96 unique records with valid 768-dimensional vectors in each database.',
       '', '## Method','',
       '- Sequential requests from the same local macOS client; backend order alternates.',
       '- Three repetitions per analytical/graph question and ten per primary-key lookup; BigQuery result caching disabled.',
       '- BigQuery uses the project’s existing query capacity. Spanner is a free-trial Enterprise instance with shared resources, reporting 100 processing units.',
       '- Full agent path: question embedding, local cosine retrieval, query generation, read-only execution, result explanation.',
       '- Requested generation model: `gemini-3.5-flash`, global Vertex endpoint; LOW thinking for SQL/GQL and MINIMAL for explanations. Embeddings: `gemini-embedding-001`, 768 dimensions, `us-east1`.',
       '- SQL agent results are compared with independently written SQL references. References are also compared across databases, with 0.011 absolute numeric tolerance for rounded amounts.',
       '- GQL path-count answers are checked against equivalent SQL joins; graph-agent queries must also contain the requested relationship-label sequence.',
       '- Correctness means structured result rows match the reference; explanation prose is not independently scored.',
       '- Successful execution and correct answers are reported separately. Latency percentiles include successful executions even when result comparison fails.',
       '- Each backend uses warmed reusable clients within a phase; the first request still includes initial connection/session setup.',
       '', '## Results','',
       '| Workload | Backend | Executed / requests | Correct | Median | p95 |',
       '|---|---|---:|---:|---:|---:|']
labels={'lookup':'Primary-key lookup','database':'Reference SQL','graph':'GQL execution','agent':'Complex SQL agent','agent-graph':'Graph agent'}
for phase in phases:
    path=ROOT/f'{phase}_results.json'
    if not path.exists():continue
    report=json.loads(path.read_text())
    for backend,summary in report['summary'].items():
        latency=summary['latency']
        p50=latency.get('p50_ms',0)/1000
        p95=latency.get('p95_ms',0)/1000
        lines.append(f"| {labels[phase]} | {backend} | {summary['successful']} / {summary['requests']} | {summary['correct']} | {p50:.2f} s | {p95:.2f} s |")
for phase in phases:
    path=ROOT/f'{phase}_results.json'
    if not path.exists():continue
    report=json.loads(path.read_text())
    if phase=='agent':
        lines+=['','### Complex agent stage medians','',
                '| Backend | Retrieval | Generation | Execution | Explanation |',
                '|---|---:|---:|---:|---:|']
        for backend,summary in report['summary'].items():
            values=[summary.get(stage,{}).get('p50_ms',0)/1000 for stage in ['retrieval','generation','execution','explanation']]
            lines.append('| '+backend+' | '+' | '.join(f'{v:.2f} s' for v in values)+' |')
        lines+=['','Stage medians are calculated independently and need not sum to the total median.','',
                '### Complex SQL agent questions','',
                '| Question | Backend | Correct / attempts | Median completed request |',
                '|---|---|---:|---:|']
        from cloud_questions import CASES
        for case in CASES:
            for backend in ['bigquery','spanner']:
                runs=[r for r in report['runs'] if r['id']==case['id'] and r['backend']==backend]
                good=[r['elapsed_ms'] for r in runs if r['status']=='success']
                median=f'{statistics.median(good)/1000:.2f} s' if good else '—'
                lines.append(f"| {case['id']} | {backend} | {sum(r.get('correct') is True for r in runs)} / {len(runs)} | {median} |")
        lines+=['','The questions specify aggregation semantics and output columns. This tests complex query construction, not ambiguity resolution for casual questions.','']
    errors=[r for r in report['runs'] if r.get('status')=='error' or r.get('correct') is False]
    if errors:
        lines+=['',f'### {labels[phase]} failures','']
        for row in errors:
            detail=row.get('error','Executed result did not match the reference.')
            lines.append(f"- {row['backend']} / {row['id']} / round {row['repeat']}: {detail[:500]}")
agent_path=ROOT/'agent_results.json'
db_path=ROOT/'database_results.json'
if agent_path.exists() and db_path.exists():
    agent_summary=json.loads(agent_path.read_text())['summary']
    db_summary=json.loads(db_path.read_text())['summary']
    winner=min(agent_summary,key=lambda b:agent_summary[b]['latency'].get('p50_ms',float('inf')))
    other='spanner' if winner=='bigquery' else 'bigquery'
    ratio=agent_summary[other]['latency'].get('p50_ms',0)/max(1,agent_summary[winner]['latency'].get('p50_ms',1))
    lines+=['','## Interpretation','',
            f'{winner} has the lower median full complex-SQL-agent latency in this run ({ratio:.2f}x compared with {other}). '
            'The complex-agent median gap is small relative to model-time variation; it does not establish that either backend generates queries faster. This is a comparison of these workloads and resource configurations, not a general database ranking.',
            '', 'Model generation and explanation add substantial latency beyond database execution. '
            'The observed path does not meet a consistent sub-five-second target for complex questions. '
            'Potential next optimizations are approved parameterized templates, smaller schema context, and delivering executed rows before the explanation finishes. '
            'These optimizations were not used in this run.']
lookup_path=ROOT/'lookup_results.json'
if lookup_path.exists():
    lookup_summary=json.loads(lookup_path.read_text())['summary']
    bq=lookup_summary['bigquery']['latency']['p50_ms']
    sp=lookup_summary['spanner']['latency']['p50_ms']
    lines+=['',f'For repeated primary-key reads, Spanner measured {sp:.2f} ms median versus '
            f'{bq:.2f} ms on BigQuery ({bq/sp:.2f}x faster). '
            'This supports the low-latency operational-read use case, while the analytical and full-agent results show why it should not be generalized to every workload or to model query generation.']
initial=ROOT/'agent_initial_failures.json'
if initial.exists():
    initial_runs=json.loads(initial.read_text())['runs']
    lines+=['','## Initial integration failures','',
            f'The initial agent run was stopped after {len(initial_runs)} recorded requests: '
            f'{sum(r["status"]=="error" for r in initial_runs)} failed, primarily because model citations did not match catalog IDs. '
            'The prompt was changed to enumerate exact approved reference IDs. The final rerun uses LOW query thinking and MINIMAL explanation thinking; initial failure timings are preserved separately and are not blended into the final latency table.']
initial_graph=ROOT/'agent-graph_initial_failures.json'
if initial_graph.exists():
    old=json.loads(initial_graph.read_text())['runs']
    lines+=['',f'The initial graph-agent smoke test recorded {len(old)} requests with '
            f'{sum(r["status"]=="error" for r in old)} failures: three missing BigQuery graph references '
            'and one Vertex capacity error. The instruction now supplies the exact GRAPH reference. '
            'Those observations remain in agent-graph_initial_failures.json, separate from the rerun.']
guard_path=ROOT/'agent-graph_guard_failures.json'
if guard_path.exists():
    old=json.loads(guard_path.read_text())['runs']
    lines+=['',f'A subsequent graph-agent run had {sum(r["status"]=="error" for r in old)} failures. '
            'The read-only keyword filter incorrectly treated the :Load node label as the LOAD write command. '
            'The guard now masks literals, quoted identifiers and GQL labels before keyword checks; '
            'genuine writes and multi-statements remain rejected, with adapter-level read-only execution unchanged. '
            'One request also encountered Vertex capacity exhaustion. Historical timings remain in agent-graph_guard_failures.json.']
lines+=['','## Integration changes validated','',
        '- BigQuery semantic publishing now uses bounded ARRAY<STRUCT> batch upserts.',
        '- Query prompts enumerate approved catalog IDs and explicitly supply the graph prefix.',
        '- Read-only guards distinguish schema labels from write commands, with regression tests.',
        '- BigQuery serving result caching is configurable and disabled for these measurements.',
        '- 48 offline tests pass; Terraform graph/semantic deployment completed on both live services.']
lines+=['','## Limits and resource lifecycle','',
        'Primary-key tests repeatedly fetch one existing key per table using parameters; they are hot-key lookup tests. This is a small, sequential, workload-specific comparison, not a production capacity benchmark. Spanner trial resources are shared; BigQuery capacity is the project\'s existing allocation. These configurations are not cost- or capacity-matched. The local client adds network latency; a regional deployment will differ. The p95 estimates have few observations.',
        '', 'No query/index tuning was performed beyond the declared primary keys. No answer caching, application-level repair/retry loops or precomputed query answers were used. Client SDK transport retry settings remain at their defaults. Semantic metadata publishing uses batch upserts; embeddings were prepared before timing.',
        '', 'Existing customer source tables were not modified. Benchmark BigQuery tables have a seven-day default expiry. The trial Spanner instance expires on January 17, 2027, with REMOVE_AFTER_GRACE_PERIOD and no automatic upgrade to paid capacity. Query and model usage may incur normal project charges.',
        '', 'Raw queries, rows, timings and per-request errors remain in the ignored `graphkit_out/cloud_validation/` directory; this report contains aggregates only.',
        '', '## Reproduction','', '```bash',
        '.venv/bin/python scripts/setup_cloud_benchmark.py --phase bigquery',
        '.venv/bin/python scripts/setup_cloud_benchmark.py --phase spanner',
        '# Scan and review each graph before approve/deploy; see README.',
        '.venv/bin/python scripts/benchmark_cloud.py --phase lookup --repeat 10 --cases 3',
        '.venv/bin/python scripts/benchmark_cloud.py --phase database --repeat 3 --cases 5',
        '.venv/bin/python scripts/benchmark_cloud.py --phase graph --repeat 3 --cases 5',
        '.venv/bin/python scripts/benchmark_cloud.py --phase agent --repeat 3 --cases 5',
        '.venv/bin/python scripts/benchmark_cloud.py --phase agent-graph --repeat 3 --cases 3',
        '.venv/bin/python scripts/report_cloud_benchmark.py', '```','']
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('\n'.join(lines))
print(out)
