# Customers_data BigQuery ML embeddings and agent benchmark — October 19, 2026

Project: `premium-odyssey-508202-k9`; source: `Customers_data`; region: `us-east1`.

## Created resources

- Remote model: `premium-odyssey-508202-k9.Customers_data.graphkit_catalog_embedding`.
- Connection: `premium-odyssey-508202-k9.us-east1.graphkit-schema-embeddings`; its service identity has `roles/aiplatform.user`.
- Persisted vector table: `premium-odyssey-508202-k9.Customers_data.GraphkitSemantic_bqml_d75fa3c170ff`; input text is in the same name with `_input` appended.
- **167 successful embeddings**, comprising 13 tables, 139 columns, 7 nodes and 8 edges.
- Embedding model: `gemini-embedding-001`, **768 dimensions**, document task `RETRIEVAL_DOCUMENT`.
- One-time vector generation and verification: **6.86 s**. This is setup time, excluded from agent latency.
- Original business records remain unchanged and are not embedded.

## Method

- Both paths use the exact same BigQuery-generated document vectors and catalog version.
- Native path: a BigQuery job runs `AI.GENERATE_EMBEDDING` for the question and exact cosine `VECTOR_SEARCH` over the stored catalog. No ANN index.
- Local path: Vertex embeds the question using the same model/dimensions; local cosine search reads the copied document vectors.
- Both paths then use the same DatasetAgent, original BigQuery business tables, read-only SQL execution and evidence explanation.
- Requested generation model: `gemini-3.5-flash`; LOW query thinking and MINIMAL explanation thinking.
- Returned model versions: `gemini-3.5-flash`.
- Seven question cases: five complex aggregations plus two short alias questions, with three repetitions per path. Path order alternates.
- Correctness compares structured result rows against separately written SQL, with 0.011 absolute tolerance for rounded numeric values. Explanation prose is not independently scored.
- Source metadata is scanned without row sampling. Existing reviewed freight graph mappings are translated to original physical names; no graph is deployed in Customers_data.
- Test vocabulary reuses reviewed table aliases and literal column-name aliases. No new business calculation definitions are invented. Production semantic approval remains separate.
- Sequential local-client measurements, reusable clients, result cache disabled, no answer cache or application repair loops. This is not a concurrent-load test.

## Full agent results

| Retrieval path | Executed / requests | Correct | Median | p95 | Correct-only median |
|---|---:|---:|---:|---:|---:|
| Native BQML + BigQuery vector search | 20 / 21 | 20 | 7.80 s | 10.08 s | 7.80 s |
| Vertex question embedding + local vector search | 20 / 21 | 20 | 6.39 s | 12.39 s | 6.39 s |

Latency statistics above include successful executions even if the answer was incorrect; correct-only medians are reported separately. Failed requests remain in the detailed results.

### Stage medians

| Path | Retrieval | Query generation | Database execution | Explanation |
|---|---:|---:|---:|---:|
| Native BQML + BigQuery vector search | 1.48 s | 3.25 s | 0.78 s | 2.05 s |
| Vertex question embedding + local vector search | 0.35 s | 2.97 s | 0.81 s | 1.92 s |

Stage medians are independent and need not sum to the total median.

### Per-question results

| Case | Path | Correct / attempts | Median successful response |
|---|---|---:|---:|
| customer_lane_margin | bigquery_vector | 3 / 3 | 10.08 s |
| customer_lane_margin | local_vector | 3 / 3 | 7.00 s |
| facility_operator_delays | bigquery_vector | 2 / 3 | 9.15 s |
| facility_operator_delays | local_vector | 3 / 3 | 6.48 s |
| customer_service | bigquery_vector | 3 / 3 | 8.81 s |
| customer_service | local_vector | 2 / 3 | 10.43 s |
| driver_fuel_detention | bigquery_vector | 3 / 3 | 7.80 s |
| driver_fuel_detention | local_vector | 3 / 3 | 6.57 s |
| lane_efficiency | bigquery_vector | 3 / 3 | 7.21 s |
| lane_efficiency | local_vector | 3 / 3 | 5.45 s |
| alias_freight | bigquery_vector | 3 / 3 | 5.97 s |
| alias_freight | local_vector | 3 / 3 | 5.06 s |
| alias_diesel | bigquery_vector | 3 / 3 | 7.59 s |
| alias_diesel | local_vector | 3 / 3 | 5.48 s |

## Alias retrieval probes

| Path | Expected table in top 8 | Median retrieval time |
|---|---:|---:|
| Native BQML + BigQuery vector search | 4 / 4 | 1.85 s |
| Vertex question embedding + local vector search | 4 / 4 | 0.29 s |

The probes cover shippers/consignments, operators/journeys, diesel purchases, and operational events/depots. Retrieval relevance is measured separately from complete-answer correctness.

## Failures and correctness

- Errors: **2**, including **2** model-capacity 429 errors.
- Abstentions: **0**; successfully executed but mismatched results: **0**.
- Failures remain in the counts; no application retries or repairs hide them. Detailed errors stay in the ignored results.

Offline validation: **57 tests passed**, including remote retrieval, approved-metadata enforcement and parameterized question handling.

## Interpretation and limits

The measured retrieval-stage results are the useful comparison: BigQuery persists and searches the vectors successfully, while local retrieval avoids a BigQuery job on each question. Total-response differences also include model-time variation and must not be attributed entirely to retrieval. Use this evidence to choose a serving path; neither path establishes a sub-second complete-answer guarantee.

The sample is small, the queries are sequential, and source data is not pinned to a historical snapshot across the full benchmark. This does not establish throughput, production p95/p99, or accuracy on ambiguous questions. No comparison to Spanner capacity was performed in this run.

Catalog tables and the model persist in Customers_data and incur normal storage/query/model charges. Discovery excludes the GraphkitSemantic_ prefix; the hourly replication allowlist excludes these metadata tables. New records require no schema-embedding refresh; schema or reviewed semantic changes require a new catalog revision.

## Inspect the stored catalog

```sql
SELECT item_id, kind, table_name, object_name, aliases,
       ARRAY_LENGTH(embedding) AS dimensions, status
FROM `premium-odyssey-508202-k9.Customers_data.GraphkitSemantic_bqml_d75fa3c170ff`
ORDER BY kind, item_id;
```

SQL, detailed queries/answers, vectors and raw comparison results remain in ignored `graphkit_out/bqml_customers/`.

## Reproduce

```bash
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py prepare
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py embed
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py benchmark --repeat=3
PYTHONPATH=. .venv/bin/python scripts/report_bqml_catalog.py
```

References: [BQML embedding generation](https://docs.cloud.google.com/bigquery/docs/generate-text-embedding), [BigQuery semantic search tutorial](https://docs.cloud.google.com/bigquery/docs/vector-index-text-search-tutorial).
