# Reviewed semantic dataset agents

## Goal
Connect an existing relational dataset, propose a graph and semantic descriptions,
let a developer approve both, and expose a question-answering agent over the
approved dataset. Supply-chain use cases across industries are supported through
schema metadata and editable business vocabulary, not fixed entity names.

## Requirements
- Preserve existing scan, draft, confirmation, Terraform and benchmark commands.
- Catalog every scanned table and column, including tables excluded from the graph.
- Propose descriptions and aliases with optional Gemini assistance; never invent
  schema objects or approve AI output automatically.
- Bind semantic approval and embeddings to an exact graph/schema revision.
- Embed approved text with an explicit model identifier; retrieve by cosine
  similarity and preserve relationship context for query generation.
- Generate reviewable semantic-table DDL alongside graph DDL for BigQuery/Spanner.
  Populate semantic rows through an explicit parameterized publishing command.
- Answer questions using approved metadata, SQL or GQL, executed results, schema
  references and measured stage timings. Abstain when context is insufficient.
- Use database-enforced read-only execution; never trust a prompt or regex alone.
- Support current BigQuery, Spanner (GoogleSQL), SQLite adapters. Other databases
  require adapters; arbitrary databases are not automatically supported.
- Keep ingestion, approval and embedding out of the serving request path.
- Initial latency objective: p50 <=4s, p95 <=10s for routine questions under a
  defined load; this is a target, not a performance guarantee.

## Acceptance
Offline tests cover review gates, stale artifacts, aliases, embedding integrity,
query rejection and executed-answer evidence. Existing tests continue to pass.
Cloud deployment and latency must be validated against real databases separately.

## Delivered in this branch
- `semantic propose/approve/embed/publish` CLI lifecycle and editable JSON catalog.
- Optional Gemini semantic descriptions/aliases and explicit embedding provider.
- Exact-revision approval gates and embedding integrity checks.
- BigQuery/Spanner semantic-table Terraform plus versioned vector publishing.
- Local cosine retrieval, approved relationship context and read-only SQL/GQL QA.
- ADK-compatible `dataset_tools`, direct `DatasetAgent`, and `ask` CLI.
- Full-path `agent-bench` p50/p95/p99 metrics with failure/abstention counts.
- Offline tests and generated Terraform validation for both cloud backends.
- Native BigQuery-to-Spanner batch replication, explicit keys/schema, a shared
  source snapshot, overlap protection and hourly scheduling. See
  `pipelines/customers_to_spanner/README.md` for deployment and operating limits.
- BigQuery ML schema-embedding generation and native exact vector retrieval,
  exposed through an optional approved-context retriever on DatasetAgent.
- Full-catalog agent mode without embedding artifacts or calls, plus native
  Spanner cosine retrieval with typed vector parameters and version/model filters.

## Live validation
- Isolated copies of Customers_data loaded into BigQuery and a free-trial Spanner instance.
- Graph and semantic-table Terraform applied successfully on both backends.
- Independent SQL, GQL and full-agent timing/correctness measurements are documented in reports/.
- All 13 Customers_data tables replicated into `customers_serving`: 549,586 rows,
  with matching counts, column aggregates and ordered samples. The initial native
  export workflow completed in 149.26 seconds; hourly refresh is enabled.
- BigQuery ML generated 167 schema-object embeddings (including all 139 columns)
  in Customers_data. Of 42 agent requests over seven cases, 40 completed and
  matched independent SQL; two failed with model-capacity 429 errors. See the
  BQML report for native/local retrieval and full-agent timing comparisons.
- Matched four-way no-embedding/native-vector comparison across BigQuery and
  Spanner: 84 requests over seven cases, 81 completed/reference-matched answers
  and three model-capacity errors. Markdown and aggregate JSON baselines are
  preserved under `reports/retrieval-comparison-2026-10-19.*`.

## Remaining production work
- Expand live BigQuery/Spanner validation beyond the freight benchmark; add workload quality and ambiguity evaluations.
- Additional database adapters and ANN/index deployment.
- Semantic review in the browser (JSON review is implemented).
- Concurrent serving/load tests, deployment-specific IAM and latency tuning.
