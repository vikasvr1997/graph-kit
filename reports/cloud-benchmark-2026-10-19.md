# BigQuery and Spanner live benchmark — October 19, 2026

Project: `premium-odyssey-508202-k9`. Source: `Customers_data` (unchanged).
Targets: BigQuery `graphkit_validation`; Spanner `graphkit-benchmark/graphkit_validation`.
Both targets are in `us-east1`, with 538,540 identical projected rows across eight tables.
Graphs: seven node labels and eight edges. Semantic catalogs: 96 objects each; remote verification found exactly 96 unique records with valid 768-dimensional vectors in each database.

## Method

- Sequential requests from the same local macOS client; backend order alternates.
- Three repetitions per analytical/graph question and ten per primary-key lookup; BigQuery result caching disabled.
- BigQuery uses the project’s existing query capacity. Spanner is a free-trial Enterprise instance with shared resources, reporting 100 processing units.
- Full agent path: question embedding, local cosine retrieval, query generation, read-only execution, result explanation.
- Requested generation model: `gemini-3.5-flash`, global Vertex endpoint; LOW thinking for SQL/GQL and MINIMAL for explanations. Embeddings: `gemini-embedding-001`, 768 dimensions, `us-east1`.
- SQL agent results are compared with independently written SQL references. References are also compared across databases, with 0.011 absolute numeric tolerance for rounded amounts.
- GQL path-count answers are checked against equivalent SQL joins; graph-agent queries must also contain the requested relationship-label sequence.
- Correctness means structured result rows match the reference; explanation prose is not independently scored.
- Successful execution and correct answers are reported separately. Latency percentiles include successful executions even when result comparison fails.
- Each backend uses warmed reusable clients within a phase; the first request still includes initial connection/session setup.

## Results

| Workload | Backend | Executed / requests | Correct | Median | p95 |
|---|---|---:|---:|---:|---:|
| Primary-key lookup | bigquery | 30 / 30 | 30 | 0.54 s | 0.80 s |
| Primary-key lookup | spanner | 30 / 30 | 30 | 0.07 s | 0.20 s |
| Reference SQL | bigquery | 15 / 15 | 15 | 0.67 s | 1.10 s |
| Reference SQL | spanner | 15 / 15 | 15 | 1.96 s | 5.70 s |
| GQL execution | bigquery | 15 / 15 | 15 | 0.77 s | 1.29 s |
| GQL execution | spanner | 15 / 15 | 15 | 1.09 s | 2.62 s |
| Complex SQL agent | bigquery | 15 / 15 | 15 | 9.71 s | 39.55 s |
| Complex SQL agent | spanner | 15 / 15 | 15 | 9.43 s | 51.20 s |
| Graph agent | bigquery | 9 / 9 | 9 | 5.70 s | 7.77 s |
| Graph agent | spanner | 9 / 9 | 9 | 5.70 s | 6.70 s |

### Complex agent stage medians

| Backend | Retrieval | Generation | Execution | Explanation |
|---|---:|---:|---:|---:|
| bigquery | 0.40 s | 5.92 s | 0.88 s | 2.20 s |
| spanner | 0.39 s | 4.40 s | 1.75 s | 1.88 s |

Stage medians are calculated independently and need not sum to the total median.

### Complex SQL agent questions

| Question | Backend | Correct / attempts | Median completed request |
|---|---|---:|---:|
| customer_lane_margin | bigquery | 3 / 3 | 9.71 s |
| customer_lane_margin | spanner | 3 / 3 | 18.02 s |
| facility_operator_delays | bigquery | 3 / 3 | 8.03 s |
| facility_operator_delays | spanner | 3 / 3 | 8.88 s |
| customer_service | bigquery | 3 / 3 | 16.40 s |
| customer_service | spanner | 3 / 3 | 14.48 s |
| driver_fuel_detention | bigquery | 3 / 3 | 6.16 s |
| driver_fuel_detention | spanner | 3 / 3 | 8.79 s |
| lane_efficiency | bigquery | 3 / 3 | 14.23 s |
| lane_efficiency | spanner | 3 / 3 | 6.39 s |

The questions specify aggregation semantics and output columns. This tests complex query construction, not ambiguity resolution for casual questions.


## Interpretation

spanner has the lower median full complex-SQL-agent latency in this run (1.03x compared with bigquery). The complex-agent median gap is small relative to model-time variation; it does not establish that either backend generates queries faster. This is a comparison of these workloads and resource configurations, not a general database ranking.

Model generation and explanation add substantial latency beyond database execution. The observed path does not meet a consistent sub-five-second target for complex questions. Potential next optimizations are approved parameterized templates, smaller schema context, and delivering executed rows before the explanation finishes. These optimizations were not used in this run.

For repeated primary-key reads, Spanner measured 67.83 ms median versus 544.40 ms on BigQuery (8.03x faster). This supports the low-latency operational-read use case, while the analytical and full-agent results show why it should not be generalized to every workload or to model query generation.

## Initial integration failures

The initial agent run was stopped after 4 recorded requests: 4 failed, primarily because model citations did not match catalog IDs. The prompt was changed to enumerate exact approved reference IDs. The final rerun uses LOW query thinking and MINIMAL explanation thinking; initial failure timings are preserved separately and are not blended into the final latency table.

The initial graph-agent smoke test recorded 6 requests with 4 failures: three missing BigQuery graph references and one Vertex capacity error. The instruction now supplies the exact GRAPH reference. Those observations remain in agent-graph_initial_failures.json, separate from the rerun.

A subsequent graph-agent run had 12 failures. The read-only keyword filter incorrectly treated the :Load node label as the LOAD write command. The guard now masks literals, quoted identifiers and GQL labels before keyword checks; genuine writes and multi-statements remain rejected, with adapter-level read-only execution unchanged. One request also encountered Vertex capacity exhaustion. Historical timings remain in agent-graph_guard_failures.json.

## Integration changes validated

- BigQuery semantic publishing now uses bounded ARRAY<STRUCT> batch upserts.
- Query prompts enumerate approved catalog IDs and explicitly supply the graph prefix.
- Read-only guards distinguish schema labels from write commands, with regression tests.
- BigQuery serving result caching is configurable and disabled for these measurements.
- 48 offline tests pass; Terraform graph/semantic deployment completed on both live services.

## Limits and resource lifecycle

Primary-key tests repeatedly fetch one existing key per table using parameters; they are hot-key lookup tests. This is a small, sequential, workload-specific comparison, not a production capacity benchmark. Spanner trial resources are shared; BigQuery capacity is the project's existing allocation. These configurations are not cost- or capacity-matched. The local client adds network latency; a regional deployment will differ. The p95 estimates have few observations.

No query/index tuning was performed beyond the declared primary keys. No answer caching, application-level repair/retry loops or precomputed query answers were used. Client SDK transport retry settings remain at their defaults. Semantic metadata publishing uses batch upserts; embeddings were prepared before timing.

Existing customer source tables were not modified. Benchmark BigQuery tables have a seven-day default expiry. The trial Spanner instance expires on January 17, 2027, with REMOVE_AFTER_GRACE_PERIOD and no automatic upgrade to paid capacity. Query and model usage may incur normal project charges.

Raw queries, rows, timings and per-request errors remain in the ignored `graphkit_out/cloud_validation/` directory; this report contains aggregates only.

## Reproduction

```bash
.venv/bin/python scripts/setup_cloud_benchmark.py --phase bigquery
.venv/bin/python scripts/setup_cloud_benchmark.py --phase spanner
# Scan and review each graph before approve/deploy; see README.
.venv/bin/python scripts/benchmark_cloud.py --phase lookup --repeat 10 --cases 3
.venv/bin/python scripts/benchmark_cloud.py --phase database --repeat 3 --cases 5
.venv/bin/python scripts/benchmark_cloud.py --phase graph --repeat 3 --cases 5
.venv/bin/python scripts/benchmark_cloud.py --phase agent --repeat 3 --cases 5
.venv/bin/python scripts/benchmark_cloud.py --phase agent-graph --repeat 3 --cases 3
.venv/bin/python scripts/report_cloud_benchmark.py
```
