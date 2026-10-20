# ADK Cloud Run preview validation — 2026-10-20

The new `feature/adk-dataset-agent` branch runs the dataset QA workflow through
ADK 2.12.0. The existing `graphkit` service was not changed.

- Service: `graphkit-adk`, `us-central1`, private Cloud Run IAM authentication.
- Revision: `graphkit-adk-00005-vpj`.
- Image: `sha256:9e86f65a82fe6e0200d518b786f5471d84110febb54f8fd1a40b56fd356eaa34`.
- Preview default: `GRAPHKIT_MODEL=gemini-2.5-flash`, global Vertex AI endpoint.
- `GRAPHKIT_DATASET_ENGINE=adk`, `CHAT_ENABLED=false`.
- One maximum instance, 1 CPU, 1 GiB memory, concurrency 4.
- Workspaces and the BigQuery dataset contain synthetic data only.

## Live checks

Both approved workspaces answered “How many suppliers are there?” using SQL,
with full approved catalog context and embeddings disabled. Both returned the
expected count of 8 and cited `table:suppliers`. BigQuery used the native ADK
BigQuery execution tool, with writes blocked and a 1 GB billing cap. SQLite used
its database-enforced read-only adapter within the ADK workflow.

| Workspace | Expected and actual count | HTTP elapsed | Server workflow total | Result |
| --- | --- | --- | --- | --- |
| SupplyChain | 8 | 6.81 s | 3.06 s | passed |
| BigQueryDemo | 8 | 5.15 s | 3.84 s | passed |

The [raw results](adk-cloud-preview-2026-10-20.json) contain generated queries,
references, explanations and stage timings. HTTP elapsed includes startup,
artifact loading and network overhead outside the workflow timer. These are
single smoke-test observations, not a latency benchmark or a quality evaluation
across arbitrary questions.

The UI served HTTP 200. Its model catalog reported Gemini 2.5 Flash as the
configured default, and capabilities reported graph enabled and chat disabled.
The authenticated local preview is http://localhost:8091.

## Offline checks

- 93 tests passed, including the existing graph, chat and isolation regressions.
- ADK Runner tests cover approved-context retrieval, structured planning,
  executed evidence, abstention and explanation.
- Writes, out-of-scope tables and invalid citations are rejected before execution.
- Deterministic comparisons preserve the legacy response evidence for a fixed plan.
- Tests verify native read-only/cost/row settings, fixed workspace targeting,
  async API dispatch, model output limits and configurable generation defaults.
- The React production build passed; it retains its existing large-bundle warning.

## Limits and observations

Spanner toolset wiring and settings were tested offline, including its read-only
capability and fixed database target. Live Spanner queries and GQL were not
validated in this deployment. Live embedding generation/retrieval was not part
of these smoke tests; approved catalog and embedding revision checks remain in
place when embeddings are enabled.

Earlier Gemini 3.5 Flash calls returned correct supplier counts but had variable
latency, including a 141-second server workflow. A later bounded validation did
not complete successfully. The preview therefore explicitly selects Gemini 2.5
Flash rather than silently substituting models after a failure. Model output
and HTTP requests are bounded; model availability/latency still varies.

The initial Vertex AI permission denial disappeared after the explicitly approved
runtime roles propagated. A client-lifecycle warning observed in the first image
was addressed with async API execution and explicit model-client cleanup.

ADK 2.12.0 marks SequentialAgent deprecated and Spanner toolsets experimental;
the dependency is pinned. File-based workspaces remain a single-user preview
mechanism, not transactional multi-user persistence.

See [ADK_DATASET.md](../ADK_DATASET.md) for setup, engine selection, IAM scope,
synthetic data seeding and reproducible live-check commands.
