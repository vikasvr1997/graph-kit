# ADK dataset-agent feature

Branch: `feature/adk-dataset-agent`.

The dataset question-answering runtime now uses Google's ADK. Graph creation
still uses the existing scan/infer/review workflows. The conversational chat
feature remains disabled by default.

## Execution

`graphkit/graph/agents/dataset_agent.py` builds an ADK `SequentialAgent` with:

1. Approved-context retrieval: load the reviewed schema, graph and semantic catalog.
2. ADK `LlmAgent` planner: produce a structured query plan, or abstain.
3. Validated execution: enforce the requested mode, read-only query, approved
   table/graph scope and valid catalog citations before any database tool runs.
4. ADK `LlmAgent` explanation: explain the executed rows; skip this stage on abstention.

Every question receives an isolated ADK Runner and session. The response preserves
query, rows, references, catalog revision and timing fields, and adds `engine: adk`.
Planning is capped at 4096 output tokens and explanation at 2048. Gemini 3
models use LOW thinking, and model HTTP requests have a 90-second timeout with
no automatic retry.
Synchronous callers use `.answer(...)`; async callers use `await .answer_async(...)`.

BigQuery execution uses ADK's native `BigQueryToolset`, with writes blocked,
a maximum-bytes-billed cap and bounded result rows. Spanner execution uses ADK's
native `SpannerToolset` with DATA_READ capability and dictionary results. Only
`execute_sql` is selected, and the planner cannot invoke it before validation.
SQLite uses the existing database-enforced read-only adapter.

Native tools are used here; an external MCP server is not required or configured.
Project-specific approval, schema and query validation remain GraphKit code.

## Installation

```sh
pip install -e '.[api,adk,bigquery,spanner]'
graphkit web
```

ADK is pinned to `2.12.0` for the APIs validated by this feature. This release
marks `SequentialAgent` deprecated in favor of the newer workflow API and marks
Spanner toolsets experimental; those upstream transitions are not part of this
migration. Set `GRAPHKIT_MODEL` to configure the default generation model at server startup.
The preview uses `gemini-2.5-flash`, which passed the live checks; Gemini 3.5
produced correct early results but later hit the model request timeout.
`DatasetAgent` is the single ADK implementation used by the API, CLI, chat tools
and benchmark integrations. Approval, retrieval and query validation live in
`dataset_context.py`; they do not implement another agent. Injected `ask` callables
are adapted to ADK model requests for provider-independent tests and benchmarks.
The legacy engine has been removed. Unset `GRAPHKIT_DATASET_ENGINE` if previously
configured to `legacy`.

Approved datasets can be queried without embeddings by setting
`use_embeddings: false` in the API body. The Semantic UI uses the full approved
catalog when no embedding artifact exists. If embeddings exist, their model and
revision checks remain mandatory.

## Cloud preview

- Project: `premium-odyssey-508202-k9`
- Service: `graphkit-adk`, region `us-central1`
- URL: https://graphkit-adk-100634033534.us-central1.run.app
- Revision: `graphkit-adk-00005-vpj`
- Image digest: `sha256:9e86f65a82fe6e0200d518b786f5471d84110febb54f8fd1a40b56fd356eaa34`
- Runtime: `graphkit-adk-run@premium-odyssey-508202-k9.iam.gserviceaccount.com`
- Workspace bucket: `gs://premium-odyssey-508202-k9-graphkit-adk-workspaces`
- Synthetic BigQuery dataset: `premium-odyssey-508202-k9.graphkit_adk_demo`
- `CHAT_ENABLED=false`, `GRAPHKIT_DATASET_ENGINE=adk`
- Preview default: `GRAPHKIT_MODEL=gemini-2.5-flash`; selectable in the UI.
- Vertex AI generation endpoint: `global`.
- One maximum instance, four concurrent requests so UI requests can proceed during inference.
  Workspace files are intended for a single-user preview; concurrent production editing
  still needs transactional persistence and coordination.

The existing `graphkit` Cloud Run service is unchanged. This preview is private:

```sh
gcloud run services proxy graphkit-adk \
  --project=premium-odyssey-508202-k9 --region=us-central1 --port=8091
```

Open http://localhost:8091. `SupplyChain` is the synthetic SQLite workspace;
`BigQueryDemo` is its independently scanned BigQuery counterpart. Both have
approved graph and semantic artifacts. Select the Semantic tab to ask questions.
`/api/dataset/runtime` reports the active engine and installed ADK version.

The preview identity has the explicitly approved project roles
`roles/aiplatform.user` and `roles/bigquery.jobUser`, read access to the synthetic
BigQuery dataset only, and object access to its own workspace bucket.

## Verification

Offline tests exercise actual ADK runners with fake model responses, compare
injected and ADK model evidence for a fixed plan, verify abstention, and assert that
writes, out-of-scope tables and invalid citations fail before execution.
Native toolset configuration and fixed workspace targeting are also tested.

```sh
python -m pytest -q
cd graphkit-web && npm run build
```

Offline tests do not establish live model accuracy or Spanner compatibility for
all workloads. Live preview measurements are recorded in
[the feature report](reports/adk-cloud-preview-2026-10-20.md).

Reproduce the synthetic dataset and live checks with:

```sh
python scripts/seed_adk_demo.py --project premium-odyssey-508202-k9 \
  --reader-service-account graphkit-adk-run@premium-odyssey-508202-k9.iam.gserviceaccount.com
python scripts/validate_adk_cloud.py \
  --url https://graphkit-adk-100634033534.us-central1.run.app \
  --model gemini-2.5-flash \
  --output reports/adk-cloud-preview-2026-10-20.json
```

References: [BigQuery tools](https://adk.dev/integrations/bigquery/),
[Spanner tools](https://adk.dev/integrations/spanner/).
