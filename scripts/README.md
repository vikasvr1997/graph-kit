# Live freight benchmark

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
