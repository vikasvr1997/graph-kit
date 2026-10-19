"""Summarize live BQML testing without publishing business rows or answers."""
import json
import statistics
from collections import Counter
from pathlib import Path

ROOT = Path('graphkit_out/bqml_customers')
data = json.loads((ROOT/'benchmark.json').read_text())
if len(data['runs']) != 14*data['repeat']:
    raise ValueError('Benchmark is incomplete; wait for all seven cases on both paths.')
resource = data['resources']
catalog = json.loads((ROOT/'CustomersBqmlTest/semantic.approved.json').read_text())
kinds = Counter(item['kind'] for item in catalog['items'])
names = {'bigquery_vector': 'Native BQML + BigQuery vector search',
         'local_vector': 'Vertex question embedding + local vector search'}
out = Path('reports/bqml-customers-benchmark-2026-10-19.md')

def seconds(ms):
    return f'{ms/1000:.2f} s'

lines = ['# Customers_data BigQuery ML embeddings and agent benchmark — October 19, 2026', '',
    'Project: `premium-odyssey-508202-k9`; source: `Customers_data`; region: `us-east1`.', '',
    '## Created resources', '',
    f"- Remote model: `{resource['model']}`.",
    '- Connection: `premium-odyssey-508202-k9.us-east1.graphkit-schema-embeddings`; its service identity has `roles/aiplatform.user`.',
    f"- Persisted vector table: `{resource['table']}`; input text is in the same name with `_input` appended.",
    f"- **{resource['successful_embeddings']} successful embeddings**, comprising {kinds['table']} tables, {kinds['column']} columns, {kinds['node']} nodes and {kinds['edge']} edges.",
    f"- Embedding model: `{resource['embedding_model']}`, **768 dimensions**, document task `RETRIEVAL_DOCUMENT`.",
    f"- One-time vector generation and verification: **{seconds(resource['generation_ms'])}**. This is setup time, excluded from agent latency.",
    '- Original business records remain unchanged and are not embedded.', '',
    '## Method', '',
    '- Both paths use the exact same BigQuery-generated document vectors and catalog version.',
    '- Native path: a BigQuery job runs `AI.GENERATE_EMBEDDING` for the question and exact cosine `VECTOR_SEARCH` over the stored catalog. No ANN index.',
    '- Local path: Vertex embeds the question using the same model/dimensions; local cosine search reads the copied document vectors.',
    '- Both paths then use the same DatasetAgent, original BigQuery business tables, read-only SQL execution and evidence explanation.',
    f"- Requested generation model: `{data['generation_model']}`; LOW query thinking and MINIMAL explanation thinking.",
    f"- Returned model versions: {', '.join('`'+x+'`' for x in data.get('returned_model_versions', []))}.",
    '- Seven question cases: five complex aggregations plus two short alias questions, with three repetitions per path. Path order alternates.',
    '- Correctness compares structured result rows against separately written SQL, with 0.011 absolute tolerance for rounded numeric values. Explanation prose is not independently scored.',
    '- Source metadata is scanned without row sampling. Existing reviewed freight graph mappings are translated to original physical names; no graph is deployed in Customers_data.',
    '- Test vocabulary reuses reviewed table aliases and literal column-name aliases. No new business calculation definitions are invented. Production semantic approval remains separate.',
    '- Sequential local-client measurements, reusable clients, result cache disabled, no answer cache or application repair loops. This is not a concurrent-load test.', '',
    '## Full agent results', '',
    '| Retrieval path | Executed / requests | Correct | Median | p95 | Correct-only median |',
    '|---|---:|---:|---:|---:|---:|']
for key, summary in data['summary'].items():
    lat = summary['latency']
    correct = summary['correct_latency']
    lines.append(f"| {names[key]} | {summary['successful']} / {summary['requests']} | {summary['correct']} | "
                 f"{seconds(lat['p50_ms']) if lat else '—'} | {seconds(lat['p95_ms']) if lat else '—'} | "
                 f"{seconds(correct['p50_ms']) if correct else '—'} |")
lines += ['', 'Latency statistics above include successful executions even if the answer was incorrect; correct-only medians are reported separately. Failed requests remain in the detailed results.', '',
          '### Stage medians', '', '| Path | Retrieval | Query generation | Database execution | Explanation |',
          '|---|---:|---:|---:|---:|']
for key, summary in data['summary'].items():
    values = [seconds(summary['stages'][stage]['p50_ms']) if summary['stages'][stage] else '—'
              for stage in ['retrieval', 'generation', 'execution', 'explanation']]
    lines.append(f"| {names[key]} | "+' | '.join(values)+' |')
lines += ['', 'Stage medians are independent and need not sum to the total median.', '',
          '### Per-question results', '', '| Case | Path | Correct / attempts | Median successful response |',
          '|---|---|---:|---:|']
for case in dict.fromkeys(r['id'] for r in data['runs']):
    for key in names:
        runs = [r for r in data['runs'] if r['id'] == case and r['path'] == key]
        timings = [r['elapsed_ms'] for r in runs if r['status'] == 'success']
        lines.append(f"| {case} | {key} | {sum(r.get('correct') is True for r in runs)} / {len(runs)} | "
                     f"{seconds(statistics.median(timings)) if timings else '—'} |")
lines += ['', '## Alias retrieval probes', '', '| Path | Expected table in top 8 | Median retrieval time |',
          '|---|---:|---:|']
for key in names:
    probes = [r for r in data['retrieval_probes'] if r['path'] == key]
    values = [r['elapsed_ms'] for r in probes if 'elapsed_ms' in r]
    lines.append(f"| {names[key]} | {sum(r.get('expected_table_in_top8') is True for r in probes)} / {len(probes)} | "
                 f"{seconds(statistics.median(values)) if values else '—'} |")
errors = [r for r in data['runs'] if r['status'] == 'error']
abstentions = [r for r in data['runs'] if r['status'] == 'abstained']
mismatches = [r for r in data['runs'] if r['status'] == 'success' and not r.get('correct')]
lines += ['', 'The probes cover shippers/consignments, operators/journeys, diesel purchases, and operational events/depots. Retrieval relevance is measured separately from complete-answer correctness.', '',
    '## Failures and correctness', '',
    f"- Errors: **{len(errors)}**, including **{sum('429' in r.get('error', '') for r in errors)}** model-capacity 429 errors.",
    f'- Abstentions: **{len(abstentions)}**; successfully executed but mismatched results: **{len(mismatches)}**.',
    '- Failures remain in the counts; no application retries or repairs hide them. Detailed errors stay in the ignored results.', '',
    'Offline validation: **57 tests passed**, including remote retrieval, approved-metadata enforcement and parameterized question handling.', '',
    '## Interpretation and limits', '',
    'The measured retrieval-stage results are the useful comparison: BigQuery persists and searches the vectors successfully, while local retrieval avoids a BigQuery job on each question. Total-response differences also include model-time variation and must not be attributed entirely to retrieval. Use this evidence to choose a serving path; neither path establishes a sub-second complete-answer guarantee.', '',
    'The sample is small, the queries are sequential, and source data is not pinned to a historical snapshot across the full benchmark. This does not establish throughput, production p95/p99, or accuracy on ambiguous questions. No comparison to Spanner capacity was performed in this run.', '',
    'Catalog tables and the model persist in Customers_data and incur normal storage/query/model charges. Discovery excludes the GraphkitSemantic_ prefix; the hourly replication allowlist excludes these metadata tables. New records require no schema-embedding refresh; schema or reviewed semantic changes require a new catalog revision.', '',
    '## Inspect the stored catalog', '', '```sql',
    'SELECT item_id, kind, table_name, object_name, aliases,',
    '       ARRAY_LENGTH(embedding) AS dimensions, status',
    f"FROM `{resource['table']}`", 'ORDER BY kind, item_id;', '```', '',
    'SQL, detailed queries/answers, vectors and raw comparison results remain in ignored `graphkit_out/bqml_customers/`.', '',
    '## Reproduce', '', '```bash',
    'PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py prepare',
    'PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py embed',
    'PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py benchmark --repeat=3',
    'PYTHONPATH=. .venv/bin/python scripts/report_bqml_catalog.py', '```', '',
    'References: [BQML embedding generation](https://docs.cloud.google.com/bigquery/docs/generate-text-embedding), '
    '[BigQuery semantic search tutorial](https://docs.cloud.google.com/bigquery/docs/vector-index-text-search-tutorial).', '']
out.write_text('\n'.join(lines))
print(out)
