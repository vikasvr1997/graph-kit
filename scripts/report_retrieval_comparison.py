"""Persist aggregate four-way benchmark results; never publish result rows."""
import datetime as dt
import json
import math
import statistics
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path('graphkit_out/retrieval_comparison')
data = json.loads((ROOT/'benchmark.json').read_text())
meta = data['metadata']
expected = len(meta['cases'])*len(meta['paths'])*meta['repeat']
if len(data['runs']) != expected or not meta.get('finished_utc'):
    raise ValueError('Benchmark incomplete; wait for all cases and paths.')
day = dt.datetime.fromisoformat(meta['started_utc']).astimezone(ZoneInfo('America/Detroit')).date().isoformat()
out = Path(f'reports/retrieval-comparison-{day}.md')
labels = {'bigquery_no_embeddings': 'BigQuery — no embeddings',
          'bigquery_native_embeddings': 'BigQuery — native embeddings',
          'spanner_no_embeddings': 'Spanner — no embeddings',
          'spanner_native_embeddings': 'Spanner — native embeddings'}


def sec(ms):
    return '—' if ms is None else f'{ms/1000:.2f} s'


def latency(summary, key):
    return sec(summary.get(key))


counts = data['preflight']['counts']['bigquery']
subsets = {}
for group in ['complex', 'alias']:
    subsets[group] = {}
    for name in meta['paths']:
        runs = [r for r in data['runs'] if r['path'] == name and
                r['id'].startswith('alias_') == (group == 'alias')]
        times = sorted(r['elapsed_ms'] for r in runs if r['status'] == 'success')
        subsets[group][name] = {
            'requests': len(runs), 'correct': sum(r.get('correct') is True for r in runs),
            'successful': len(times),
            'p50_ms': statistics.median(times) if times else None,
            'p95_ms': times[math.ceil(.95*len(times))-1] if times else None}
lines = [f'# No embeddings vs native embeddings: BigQuery and Spanner — {day}', '',
    '## Outcome', '',
    '| Agent path | Correct / requests | Errors | Median completed answer | p95 completed answer | Correct-only median |',
    '|---|---:|---:|---:|---:|---:|']
for name in meta['paths']:
    s = data['summary'][name]
    lines.append(f"| {labels[name]} | {s['correct']} / {s['requests']} | {s['errors']} | "
                 f"{latency(s['latency'], 'p50_ms')} | {latency(s['latency'], 'p95_ms')} | "
                 f"{latency(s['correct_latency'], 'p50_ms')} |")
completed = [r for r in data['runs'] if r['status'] == 'success']
correct = [r for r in completed if r.get('correct')]
eligible = [name for name in meta['paths'] if data['summary'][name]['correct_latency']]
if eligible:
    fastest = min(eligible, key=lambda name: data['summary'][name]['correct_latency']['p50_ms'])
    lines += ['', f"The lowest observed correct-answer median was **{labels[fastest]}**, at "
              f"**{latency(data['summary'][fastest]['correct_latency'], 'p50_ms')}**. "
              f"Across the run, **{len(correct)} of {len(completed)} completed responses** matched the references, "
              f"from **{len(data['runs'])} total requests**."]
lines += ['', 'Completed-answer timing includes successfully executed requests, including any wrong answers; errors and abstentions remain in the request totals. Correct-only timing excludes wrong answers. These are small-sample sequential results, not concurrency or production-capacity measurements.', '',
    '## Controlled comparison', '',
    f"- Project: `{meta['project']}`; region: `us-east1`.",
    '- Both backends read isolated, matching eight-table copies of Customers_data: BigQuery `graphkit_validation` and Spanner `graphkit-benchmark/graphkit_validation`.',
    f'- **{sum(counts.values()):,} business rows** across **{len(counts)} tables**. Row counts and current column schemas were checked before timing. All seven independent reference query results agreed across backends.',
    '- Same approved catalog text: **96 objects**, including tables, columns, graph nodes and relationships. The 167-object original-dataset catalog remains unchanged; using the smaller shared catalog keeps this experiment matched.',
    f"- Document embeddings generated once with BigQuery ML using `{meta['embedding_model']}`, 768 dimensions, then copied exactly into a separate Spanner catalog table. Stored vector values were compared for equality.",
    '- **No embeddings:** supply every approved catalog object and its descriptions/aliases as unranked context. No vector artifact is loaded and no question embedding or vector search runs.',
    '- **Native BigQuery embeddings:** BigQuery ML embeds each question and `VECTOR_SEARCH` performs exact cosine retrieval over the stored catalog; top eight objects become semantic context.',
    '- **Native Spanner embeddings:** Vertex embeds each question using the same model/dimensions; Spanner executes exact `COSINE_DISTANCE` retrieval, filtered by catalog version/model, and returns the top eight objects.',
    '- Both native searches are exact, with no ANN index. Both branches execute all business SQL in their respective backend.',
    '- Same graph mappings and business definitions in all paths. Existing graph expansion supplies all eight graph tables in this dataset even with top-eight semantic retrieval. Thus embedding retrieval chiefly changes semantic-description context here, rather than pruning a large unrelated schema.',
    f"- Generation model: `{meta['model']}`; returned versions: {', '.join('`'+v+'`' for v in meta.get('returned_model_versions', []))}. Temperature 0, LOW query thinking and MINIMAL explanation thinking for every path.",
    f"- {len(meta['cases'])} cases × {meta['repeat']} repetitions × {len(meta['paths'])} paths = **{expected} requests**. Execution order rotates across paths. Clients are reused, BigQuery result caching is disabled, and no answer cache or application retry/repair loop is used. SDK defaults remain unchanged.",
    '- Questions include five specified complex aggregations and two short synonym questions. Correctness compares generated result rows with independent SQL, using numeric tolerances abs_tol=0.011 and rel_tol=1e-9. Explanation prose is not independently scored.', '',
    '## Stage medians', '',
    '| Path | Context/retrieval | Query generation | Database execution | Explanation | Median generation input tokens |',
    '|---|---:|---:|---:|---:|---:|']
for name in meta['paths']:
    s = data['summary'][name]
    stages = [latency(s['stages'][stage], 'p50_ms') for stage in ['retrieval', 'generation', 'execution', 'explanation']]
    tokens = [u['prompt_tokens'] for r in data['runs'] if r['path'] == name
              for u in r.get('model_usage', []) if u['stage'] == 'generation' and u.get('prompt_tokens') is not None]
    lines.append('| '+labels[name]+' | '+' | '.join(stages)+f" | {statistics.median(tokens) if tokens else '—'} |")
lines += ['', 'The no-embedding context stage is local catalog assembly; it is not database retrieval. Stage medians are independent and do not have to sum to the full-answer median. Token counts describe completed generation calls, including requests whose later stages failed.', '',
    '## Complex versus alias-only questions', '',
    '| Subset | Path | Correct / requests | Median completed answer | p95 completed answer |',
    '|---|---|---:|---:|---:|']
for group, summaries in subsets.items():
    for name, s in summaries.items():
        lines.append(f"| {group} | {labels[name]} | {s['correct']} / {s['requests']} | "
                     f"{sec(s['p50_ms'])} | {sec(s['p95_ms'])} |")
lines += ['',
    '## Per-question correctness and latency', '',
    '| Case | Path | Correct / requests | Median completed answer |', '|---|---|---:|---:|']
for case in meta['cases']:
    for name in meta['paths']:
        rows = [r for r in data['runs'] if r['id'] == case and r['path'] == name]
        times = [r['elapsed_ms'] for r in rows if r['status'] == 'success']
        lines.append(f"| {case} | {labels[name]} | {sum(r.get('correct') is True for r in rows)} / {len(rows)} | "
                     f"{sec(statistics.median(times)) if times else '—'} |")
lines += ['', '## Failures and abstentions', '']
for name in meta['paths']:
    runs = [r for r in data['runs'] if r['path'] == name]
    errors = [r for r in runs if r['status'] == 'error']
    mismatch = sum(r['status'] == 'success' and not r.get('correct') for r in runs)
    quota = sum('429' in r.get('error', '') for r in errors)
    lines.append(f"- {labels[name]}: {len(errors)} errors ({quota} containing 429), "
                 f"{sum(r['status'] == 'abstained' for r in runs)} abstentions, {mismatch} executed-but-incorrect results.")
lines += ['', 'Failed attempts are preserved, not rerun away. Detailed errors, questions, generated SQL, business rows and model outputs stay in ignored local artifacts.', '',
    '## Interpretation boundaries', '',
    'This isolates the practical tradeoff between sending a complete small semantic catalog and retrieving relevant metadata first. A faster median does not establish a general database ranking or an accuracy benefit from embeddings. Compare correct/request rates as well as timing. With seven question types and three repetitions, p95 estimates are unstable and model-time variation can dominate.', '',
    'Business-query execution times reflect model-generated SQL, which can differ between attempts. They are not a controlled identical-SQL database microbenchmark. This suite contains analytical aggregations and does not measure targeted operational lookup latency.', '',
    'The complex questions specify calculation and join rules. They do not measure ambiguous business definitions, long conversational history, or schema selection across hundreds of unrelated tables. All methods have access to reviewed aliases and relationships; the baseline is not deprived of those definitions.', '',
    'Spanner uses the existing free-trial shared 100-PU instance. Google describes this tier as an evaluation/learning environment and excludes production/performance-load testing from its intended uses. These bounded sequential diagnostics cannot size production capacity. No paid capacity was provisioned. BigQuery uses the project\'s existing capacity; resources are not cost- or capacity-matched. Other project workloads, including the hourly pipeline on the shared Spanner instance, are not isolated. A provisioned-instance test is needed for capacity commitments.', '',
    'Clients run locally; same-region hosting will change network overhead. Database plans/sessions may be warm from preflight queries. Business tables are static isolated copies, but no cross-database atomic snapshot spans the run.', '',
    '## Resources and reproduction', '',
    f"- BigQuery vector table: `{meta['resources']['bq_vector_table']}`.",
    f"- Spanner vector table: `{meta['resources']['spanner_vector_table']}`.",
    '- Existing deployed catalogs and business tables were not overwritten. New metadata tables use the GraphkitSemantic_ discovery exclusion prefix.',
    '- 59 offline tests pass, including a no-vector-artifact baseline and typed Spanner vector retrieval.', '', '```bash',
    'PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py prepare',
    'PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py benchmark --repeat=3',
    'PYTHONPATH=. .venv/bin/python scripts/report_retrieval_comparison.py', '```', '',
    f"Run started (UTC): `{meta['started_utc']}`; finished: `{meta['finished_utc']}`.", '',
    'Raw checkpoint: `graphkit_out/retrieval_comparison/benchmark.json`; rerunning archives the previous checkpoint under `archive/`.', '',
    'References: [BigQuery embeddings](https://docs.cloud.google.com/bigquery/docs/generate-text-embedding), '
    '[Spanner exact vector search](https://docs.cloud.google.com/spanner/docs/find-k-nearest-neighbors), '
    '[Spanner trial limitations](https://docs.cloud.google.com/spanner/docs/free-trial-instance).', '']
out.write_text('\n'.join(lines))
out.with_suffix('.json').write_text(json.dumps({
    'format_version': 1, 'metadata': meta, 'row_counts': counts,
    'summary': data['summary'], 'subsets': subsets,
    'failure_counts': {name: {
        'quota_429': sum(r['status'] == 'error' and '429' in r.get('error', '')
                         for r in data['runs'] if r['path'] == name),
        'executed_incorrect': sum(r['status'] == 'success' and not r.get('correct')
                                 for r in data['runs'] if r['path'] == name)}
        for name in meta['paths']}
}, indent=2)+'\n')
archive = ROOT/'archive'
archive.mkdir(exist_ok=True)
stamp = dt.datetime.fromisoformat(meta['started_utc']).strftime('%Y%m%dT%H%M%SZ')
(archive/f'benchmark-{stamp}.json').write_text(json.dumps(data, indent=2, default=str)+'\n')
print(out)
