# Live freight benchmark

For the separate hourly 13-table replication workflow, see
[Customers_data → Spanner](../pipelines/customers_to_spanner/README.md).
`customers_pipeline.py render|run|verify` manages its metadata, execution and
source/target validation. It uses native exports rather than a Python row loader.

These scripts target `premium-odyssey-508202-k9` and deliberately use an isolated
`graphkit_validation` BigQuery dataset and Spanner database. They are opt-in:
normal tests never invoke them. Source `Customers_data` is read-only.

Prerequisites: authenticated `gcloud`, ADC (`gcloud auth application-default login`),
project billing/model access, BigQuery/Spanner/Vertex APIs, Terraform and
`pip install -e '.[dev]'`. The Spanner instance used for this run was explicitly
created as `free-instance`, `regional-us-east1`, with
`--expire-behavior=remove-after-grace-period`; it must not auto-upgrade to paid.
The database is `graphkit-benchmark/graphkit_validation`.

1. `python scripts/inspect_cloud.py` reads schema/count metadata only.
2. `python scripts/probe_vertex.py` verifies models without sending customer rows.
3. `python scripts/setup_cloud_benchmark.py --phase bigquery` creates eight
   projected table copies with seven-day expiration.
4. `python scripts/setup_cloud_benchmark.py --phase spanner` creates matching
   schema and loads those exact copied rows using idempotent key upserts.
5. For each `--backend bigquery` and `--backend spanner`, run
   `python scripts/validate_cloud.py --backend BACKEND --phase scan`, inspect
   the proposed graph, then run phases `approve`, `deploy`, `embed`, `publish`.
   Approval here is specific to the inspected test dataset. Do not apply it
   blindly to production. `deploy` actually runs Terraform apply.
6. `python scripts/benchmark_cloud.py --phase database --repeat 3 --cases 5`
   establishes independently written SQL references and cross-backend equality.
7. Run the same command with phase `graph`, `agent`, and `agent-graph` (use
   `--cases 3` for agent-graph). Run phases sequentially to avoid contention.
8. `python scripts/report_cloud_benchmark.py` writes aggregate results to reports/.

Model and query calls incur ordinary usage charges. The free-trial instance is
not representative of provisioned production capacity. Raw rows and detailed
responses stay under ignored `graphkit_out/cloud_validation/`. Reports contain
aggregates; embeddings represent metadata, not customer row contents.

Publishing on BigQuery uses bounded batch upserts. Do not run multiple publishers
concurrently. Re-runs retain old catalog versions. The benchmark disables
BigQuery result caching, alternates engine order, and measures both successful
execution and independently checked correctness. A failed or mismatched answer
must not be counted as a correct fast answer.

For operational read latency, run phase `lookup --repeat 10 --cases 3`.
After publishing, phase `verify` in validate_cloud.py checks remote catalog
uniqueness and vector dimensions. Historical failed integration runs are retained
separately from corrected final timing runs.

## BigQuery ML catalog evaluation

`benchmark_bqml_catalog.py` targets the **original** `Customers_data` dataset in
`us-east1`. It embeds schema metadata only, covering the 13 business tables on
the replication pipeline's explicit allowlist. It reuses the reviewed freight
graph mappings with the original physical names, without deploying a graph.
The catalog uses existing table aliases and literal column names with spaces;
it introduces no AI-generated metric definitions. This is a test-scoped approval,
not production semantic sign-off.

Setup requires a regional Cloud Resource connection named
`graphkit-schema-embeddings`. Grant its service account `roles/aiplatform.user`
on the model project. The deployed connection is in project
`premium-odyssey-508202-k9`, location `us-east1`. Example setup for a new environment:

```bash
bq mk --connection --connection_type=CLOUD_RESOURCE --location=us-east1 \
  --project_id=premium-odyssey-508202-k9 graphkit-schema-embeddings
bq show --connection --location=us-east1 --project_id=premium-odyssey-508202-k9 \
  --format=prettyjson graphkit-schema-embeddings
# Grant the displayed cloudResource.serviceAccountId roles/aiplatform.user.
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py prepare
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py embed
PYTHONPATH=. .venv/bin/python scripts/benchmark_bqml_catalog.py benchmark --repeat=3
PYTHONPATH=. .venv/bin/python scripts/report_bqml_catalog.py
```

`prepare` creates a remote model referencing `gemini-embedding-001` and uploads
catalog text. `embed` executes `AI.GENERATE_EMBEDDING`, preserves per-item status,
checks every vector and builds the version-bound local index from those exact
BigQuery-generated vectors. Source business tables are not modified. Catalog
input/output tables persist in Customers_data, with `GraphkitSemantic_` prefixes
so graph discovery skips them. The hourly replication allowlist also excludes them.

The benchmark compares native BQML question embedding + exact cosine
`VECTOR_SEARCH` with Vertex question embedding + local cosine search. Both use
the same document vectors, generation model, source data and SQL-only agent.
It tests alias retrieval and seven questions (five complex aggregations and two
alias questions), alternating path order. Each answer is compared with an
independent SQL reference. Result caching is disabled; requests run sequentially.
This does not establish concurrent throughput or production p95 latency.

The optional `DatasetAgent(..., retrieve_context=retriever)` hook accepts
`retriever(question, top_k)` returning scored approved catalog objects. The
BigQuery retriever pins the catalog fingerprint and the agent rejects unapproved
metadata. The local approved catalog and embedding artifacts are still required.
Detailed results, generated SQL and local workspaces remain in ignored
`graphkit_out/bqml_customers/`. Generation, inference, queries and storage incur
ordinary cloud usage charges. No ANN index is needed for this small catalog.

## Matched no-embedding/BigQuery/Spanner comparison

`benchmark_retrieval_comparison.py` compares four SQL-agent paths: BigQuery
without embeddings, BigQuery with native BQML/vector search, Spanner without
embeddings, and Spanner with native exact cosine retrieval. It uses the existing
matching eight-table `graphkit_validation` copies and the same 96-object catalog
text. This differs from the original 13-table Customers_data catalog; the smaller
shared schema makes the backend comparison controlled.

```bash
PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py prepare
PYTHONPATH=. .venv/bin/python scripts/benchmark_retrieval_comparison.py benchmark --repeat=3
PYTHONPATH=. .venv/bin/python scripts/report_retrieval_comparison.py
```

Preparation requires the earlier BQML remote model and the two reviewed freight
workspaces. It generates 96 document vectors once through BigQuery ML, copies
them into a separate Spanner catalog table and checks exact vector equality.
Existing business tables, deployed catalogs and capacity are unchanged. The
new vector tables persist and incur ordinary storage/query/model charges.

`DatasetAgent(..., embed_question=None, embedding_model=None,
use_embeddings=False)` supplies all reviewed semantic objects and aliases
without loading any embedding artifact. Native paths use top-eight semantic
retrieval. Graph-schema expansion remains identical. This tests full small
catalog context against retrieved context, not a baseline lacking schema or
business definitions.

Before timing, the runner checks current schemas, row counts and independent SQL
result equality across databases. The seven questions are each repeated three
times per path (84 requests), rotating path order. It records correctness,
failures, prompt token counts, stage timings and complete-answer medians/p95.
Requests are sequential and this does not size concurrent or production capacity;
the existing shared Spanner trial is not representative of provisioned production
resources. Do not extrapolate these diagnostics to a load-test result.

Checkpoints, business result rows, generated SQL and responses stay under ignored
`graphkit_out/retrieval_comparison/`. Reruns archive the preceding checkpoint.
The report generator refuses incomplete runs, saves an aggregate Markdown report
under `reports/` and archives the completed raw run. SDK defaults are retained;
the application does not retry or repair failed requests.

The report also saves an aggregate JSON baseline with metadata, counts and
percentiles alongside the Markdown. It contains no business result rows and can
be committed for comparison with subsequent runs.
