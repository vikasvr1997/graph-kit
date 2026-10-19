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
