# No embeddings vs native embeddings: BigQuery and Spanner — 2026-10-19

## Outcome

| Agent path | Correct / requests | Errors | Median completed answer | p95 completed answer | Correct-only median |
|---|---:|---:|---:|---:|---:|
| BigQuery — no embeddings | 20 / 21 | 1 | 10.18 s | 30.22 s | 10.18 s |
| BigQuery — native embeddings | 20 / 21 | 1 | 9.43 s | 24.69 s | 9.43 s |
| Spanner — no embeddings | 20 / 21 | 1 | 12.33 s | 23.31 s | 12.33 s |
| Spanner — native embeddings | 21 / 21 | 0 | 12.37 s | 28.83 s | 12.37 s |

The lowest observed correct-answer median was **BigQuery — native embeddings**, at **9.43 s**. Across the run, **81 of 81 completed responses** matched the references, from **84 total requests**.

Completed-answer timing includes successfully executed requests, including any wrong answers; errors and abstentions remain in the request totals. Correct-only timing excludes wrong answers. These are small-sample sequential results, not concurrency or production-capacity measurements.

## Controlled comparison

- Project: `premium-odyssey-508202-k9`; region: `us-east1`.
- Both backends read isolated, matching eight-table copies of Customers_data: BigQuery `graphkit_validation` and Spanner `graphkit-benchmark/graphkit_validation`.
- **538,540 business rows** across **8 tables**. Row counts and current column schemas were checked before timing. All seven independent reference query results agreed across backends.
- Same approved catalog text: **96 objects**, including tables, columns, graph nodes and relationships. The 167-object original-dataset catalog remains unchanged; using the smaller shared catalog keeps this experiment matched.
- Document embeddings generated once with BigQuery ML using `gemini-embedding-001`, 768 dimensions, then copied exactly into a separate Spanner catalog table. Stored vector values were compared for equality.
- **No embeddings:** supply every approved catalog object and its descriptions/aliases as unranked context. No vector artifact is loaded and no question embedding or vector search runs.
- **Native BigQuery embeddings:** BigQuery ML embeds each question and `VECTOR_SEARCH` performs exact cosine retrieval over the stored catalog; top eight objects become semantic context.
- **Native Spanner embeddings:** Vertex embeds each question using the same model/dimensions; Spanner executes exact `COSINE_DISTANCE` retrieval, filtered by catalog version/model, and returns the top eight objects.
- Both native searches are exact, with no ANN index. Both branches execute all business SQL in their respective backend.
- Same graph mappings and business definitions in all paths. Existing graph expansion supplies all eight graph tables in this dataset even with top-eight semantic retrieval. Thus embedding retrieval chiefly changes semantic-description context here, rather than pruning a large unrelated schema.
- Generation model: `gemini-3.5-flash`; returned versions: `gemini-3.5-flash`. Temperature 0, LOW query thinking and MINIMAL explanation thinking for every path.
- 7 cases × 3 repetitions × 4 paths = **84 requests**. Execution order rotates across paths. Clients are reused, BigQuery result caching is disabled, and no answer cache or application retry/repair loop is used. SDK defaults remain unchanged.
- Questions include five specified complex aggregations and two short synonym questions. Correctness compares generated result rows with independent SQL, using numeric tolerances abs_tol=0.011 and rel_tol=1e-9. Explanation prose is not independently scored.

## Stage medians

| Path | Context/retrieval | Query generation | Database execution | Explanation | Median generation input tokens |
|---|---:|---:|---:|---:|---:|
| BigQuery — no embeddings | 0.00 s | 6.76 s | 0.93 s | 2.23 s | 10009.0 |
| BigQuery — native embeddings | 1.41 s | 4.33 s | 0.88 s | 2.31 s | 5092.0 |
| Spanner — no embeddings | 0.00 s | 7.10 s | 1.02 s | 2.25 s | 9806.0 |
| Spanner — native embeddings | 0.50 s | 6.70 s | 0.64 s | 2.18 s | 4887 |

The no-embedding context stage is local catalog assembly; it is not database retrieval. Stage medians are independent and do not have to sum to the full-answer median. Token counts describe completed generation calls, including requests whose later stages failed.

## Complex versus alias-only questions

| Subset | Path | Correct / requests | Median completed answer | p95 completed answer |
|---|---|---:|---:|---:|
| complex | BigQuery — no embeddings | 15 / 15 | 11.62 s | 38.01 s |
| complex | BigQuery — native embeddings | 14 / 15 | 10.05 s | 34.18 s |
| complex | Spanner — no embeddings | 14 / 15 | 14.04 s | 34.85 s |
| complex | Spanner — native embeddings | 15 / 15 | 17.19 s | 31.66 s |
| alias | BigQuery — no embeddings | 5 / 6 | 5.84 s | 6.39 s |
| alias | BigQuery — native embeddings | 6 / 6 | 6.61 s | 8.46 s |
| alias | Spanner — no embeddings | 6 / 6 | 5.33 s | 5.65 s |
| alias | Spanner — native embeddings | 6 / 6 | 5.07 s | 5.39 s |

## Per-question correctness and latency

| Case | Path | Correct / requests | Median completed answer |
|---|---|---:|---:|
| customer_lane_margin | BigQuery — no embeddings | 3 / 3 | 30.22 s |
| customer_lane_margin | BigQuery — native embeddings | 3 / 3 | 23.66 s |
| customer_lane_margin | Spanner — no embeddings | 2 / 3 | 23.52 s |
| customer_lane_margin | Spanner — native embeddings | 3 / 3 | 19.20 s |
| facility_operator_delays | BigQuery — no embeddings | 3 / 3 | 10.00 s |
| facility_operator_delays | BigQuery — native embeddings | 2 / 3 | 9.90 s |
| facility_operator_delays | Spanner — no embeddings | 3 / 3 | 14.47 s |
| facility_operator_delays | Spanner — native embeddings | 3 / 3 | 17.19 s |
| customer_service | BigQuery — no embeddings | 3 / 3 | 11.62 s |
| customer_service | BigQuery — native embeddings | 3 / 3 | 24.10 s |
| customer_service | Spanner — no embeddings | 3 / 3 | 15.81 s |
| customer_service | Spanner — native embeddings | 3 / 3 | 17.21 s |
| driver_fuel_detention | BigQuery — no embeddings | 3 / 3 | 12.50 s |
| driver_fuel_detention | BigQuery — native embeddings | 3 / 3 | 9.52 s |
| driver_fuel_detention | Spanner — no embeddings | 3 / 3 | 13.62 s |
| driver_fuel_detention | Spanner — native embeddings | 3 / 3 | 12.62 s |
| lane_efficiency | BigQuery — no embeddings | 3 / 3 | 5.63 s |
| lane_efficiency | BigQuery — native embeddings | 3 / 3 | 8.27 s |
| lane_efficiency | Spanner — no embeddings | 3 / 3 | 9.04 s |
| lane_efficiency | Spanner — native embeddings | 3 / 3 | 5.64 s |
| alias_freight | BigQuery — no embeddings | 2 / 3 | 6.12 s |
| alias_freight | BigQuery — native embeddings | 3 / 3 | 8.03 s |
| alias_freight | Spanner — no embeddings | 3 / 3 | 5.45 s |
| alias_freight | Spanner — native embeddings | 3 / 3 | 4.79 s |
| alias_diesel | BigQuery — no embeddings | 3 / 3 | 5.46 s |
| alias_diesel | BigQuery — native embeddings | 3 / 3 | 6.28 s |
| alias_diesel | Spanner — no embeddings | 3 / 3 | 4.91 s |
| alias_diesel | Spanner — native embeddings | 3 / 3 | 5.34 s |

## Failures and abstentions

- BigQuery — no embeddings: 1 errors (1 containing 429), 0 abstentions, 0 executed-but-incorrect results.
- BigQuery — native embeddings: 1 errors (1 containing 429), 0 abstentions, 0 executed-but-incorrect results.
- Spanner — no embeddings: 1 errors (1 containing 429), 0 abstentions, 0 executed-but-incorrect results.
- Spanner — native embeddings: 0 errors (0 containing 429), 0 abstentions, 0 executed-but-incorrect results.

Failed attempts are preserved, not rerun away. Detailed errors, questions, generated SQL, business rows and model outputs stay in ignored local artifacts.

## Interpretation boundaries

This isolates the practical tradeoff between sending a complete small semantic catalog and retrieving relevant metadata first. A faster median does not establish a general database ranking or an accuracy benefit from embeddings. Compare correct/request rates as well as timing. With seven question types and three repetitions, p95 estimates are unstable and model-time variation can dominate.

Business-query execution times reflect model-generated SQL, which can differ between attempts. They are not a controlled identical-SQL database microbenchmark. This suite contains analytical aggregations and does not measure targeted operational lookup latency.

The complex questions specify calculation and join rules. They do not measure ambiguous business definitions, long conversational history, or schema selection across hundreds of unrelated tables. All methods have access to reviewed aliases and relationships; the baseline is not deprived of those definitions.

Spanner uses the existing free-trial shared 100-PU instance. Google describes this tier as an evaluation/learning environment and excludes production/performance-load testing from its intended uses. These bounded sequential diagnostics cannot size production capacity. No paid capacity was provisioned. BigQuery uses the project's existing capacity; resources are not cost- or capacity-matched. Other project workloads, including the hourly pipeline on the shared Spanner instance, are not isolated. A provisioned-instance test is needed for capacity commitments.

Clients run locally; same-region hosting will change network overhead. Database plans/sessions may be warm from preflight queries. Business tables are static isolated copies, but no cross-database atomic snapshot spans the run.

## Resources and reproduction

- BigQuery vector table: `premium-odyssey-508202-k9.Customers_data.GraphkitSemantic_comparison_b4d1ad4fed30`.
- Spanner vector table: `GraphkitSemantic_comparison_b4d1ad4fed30`.
- Existing deployed catalogs and business tables were not overwritten. New metadata tables use the GraphkitSemantic_ discovery exclusion prefix.
- 59 offline tests pass, including a no-vector-artifact baseline and typed Spanner vector retrieval.

```bash
PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py prepare
PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py benchmark --repeat=3
PYTHONPATH=. .venv/bin/python scripts/report_retrieval_comparison.py
```

Run started (UTC): `2026-10-19T18:26:41.089472+00:00`; finished: `2026-10-19T18:43:51.205701+00:00`.

Raw checkpoint: `graphkit_out/retrieval_comparison/benchmark.json`; rerunning archives the previous checkpoint under `archive/`.

References: [BigQuery embeddings](https://docs.cloud.google.com/bigquery/docs/generate-text-embedding), [Spanner exact vector search](https://docs.cloud.google.com/spanner/docs/find-k-nearest-neighbors), [Spanner trial limitations](https://docs.cloud.google.com/spanner/docs/free-trial-instance).
