# graphkit

Point it at a BigQuery dataset or a Spanner database. It samples a few rows from every table, reads the table and column descriptions, and proposes a property graph: which tables are **nodes**, which are **edges**, and which way each edge points. You review and edit the graph in a browser, confirm it, and it writes the Terraform that creates it. Then it generates test questions, runs each one as a graph query and as plain SQL, checks that the answers match, and times both.

It is standalone. Install it next to any project, or plug the finished graph into an agent with two lines (see "Use the graph from an agent").

```
scan ──▶ draft graph ──▶ edit in the UI ──▶ confirm ──▶ Terraform apply ──▶ benchmark
  ▲                                                                            │
  └──────────────── watch: new tables show up as "new" for review ◀────────────┘
```

## Try it in 5 minutes (no cloud account)

```bash
cd graph-kit
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ui]"
graphkit demo                     # made-up supply-chain data in demo/
graphkit ui                       # opens http://localhost:8501
```

In the UI, keep **Demo (SQLite)** and press **Scan tables**. You should see 5 nodes (Supplier, Part, VehicleModel, Plant, Recall) and 6 edges. The demo declares no foreign keys, so every link was found from column names, descriptions and values. One of them, `shipments.supplier_code`, has a name that matches nothing; it was found only because all its values exist in `suppliers.supplier_id`. That's why it's drawn with orange dashes: low confidence, please review.

SQLite has no graph engine, so on the demo the benchmark runs only the SQL side. Everything else works.

## Use it on BigQuery

```bash
pip install -e ".[bigquery,ui]"
gcloud auth application-default login
graphkit ui                        # pick BigQuery, enter project + dataset, Scan
```

Or from the command line:

```bash
graphkit scan --name SupplyChain --backend bigquery --project MY_PROJECT --dataset vehicle_supply_chain
graphkit show --name SupplyChain           # what it found
graphkit confirm --name SupplyChain        # approve + write Terraform (asks first)
graphkit apply --name SupplyChain --plan   # see what Terraform will do
graphkit apply --name SupplyChain          # create the graph (asks first)
graphkit bench --name SupplyChain          # GQL vs SQL: same answers? which is faster?
```

You need permission to read the dataset and run queries (`roles/bigquery.dataViewer` and `roles/bigquery.jobUser`), plus permission to create the graph in that dataset when you apply (`roles/bigquery.dataEditor`).

## Use it on Spanner

```bash
pip install -e ".[spanner,ui]"
graphkit scan --name SupplyChain --backend spanner --project P --instance I --database D
```

Spanner has no table or column comments. To give the scan descriptions, pass `--descriptions my_descriptions.json`:

```json
{"parts": {"": "Parts used to build vehicles", "supplier_id": "References suppliers"}}
```

Interleaved tables count as links to their parent. Apply runs `gcloud spanner databases ddl update`, so `gcloud` must be installed.

## How links are found

| Evidence | Confidence |
| --- | --- |
| A declared foreign key, or Spanner interleaving | 1.0 |
| A column description says "references suppliers" (also "foreign key to", "points to", "id of the") | 0.8, then adjusted by the value check |
| A column name matches another table's key: `supplier_id`, `primary_supplier_id`, or `<table>_id` when the key is `id` | 0.6, then adjusted by the value check |
| A text column whose sampled values all appear in another table's key | 0.5 |

**The value check:** for each guessed link, the kit sends the sampled values to the database and counts how many exist in the other table's key. That's one small query per guess. If fewer than half match, the guess is dropped, even when the name fits.

**Node or edge?** A table that links to exactly two other tables, and that nothing links to, becomes an **edge** between them (like `part_usage(part_id, model_id)`). Any other table with a key becomes a **node**, and each of its foreign-key columns becomes an edge from it.

**Direction:** junction tables point from their first link column to their second. Foreign keys point from the table that holds them to the table they reference. Tick **two_way** in the editor to also add the reverse edge with its own label (for example SUPPLIES for MADE_BY), so queries can go either way.

**Optional Gemini pass:** `--llm` (or the checkbox in the UI) asks Gemini to read the descriptions and suggest clearer labels (`PART_USAGE` to `USED_IN`), flip directions, and pick two-way edges. Suggestions with invalid or duplicate labels are ignored. Nothing is applied until you confirm.

## The UI

| Tab | What you do there |
| --- | --- |
| Graph | The schema as circles and arrows, like the BigQuery graph view. Click anything to see its table, keys and why it was proposed. **Data preview** draws real sampled rows and how they connect. |
| Edit | Two editable tables, one for nodes and one for edges. Add a row to create, change a cell to update, select rows and press Delete to remove, and pick edges to flip. **Save draft** checks the graph and lists any problems. |
| Review and apply | What changed since the last approval, and the exact `CREATE PROPERTY GRAPH` statement. Tick the box, then **Confirm and write Terraform**. **Terraform plan** and **Apply** run Terraform for you, and Apply needs a second tick. |
| Benchmark | Generates questions from the graph's paths (1 to 4 hops), runs each as GQL and as SQL, compares the answers, and times both. |

## Benchmark: what it proves

For every path in the graph (for example Supplier, then SUPPLIES, then Part, then USED_IN, then VehicleModel), it writes:
- a count query: "How many Supplier to VehicleModel paths are there?"
- a top-5 query: "Which 5 Suppliers reach the most different VehicleModels?"

Each one is written twice, as GQL on the graph and as SQL joins on the raw tables. **If the answers differ, the graph is wired wrong** (a wrong key, or a flipped edge). Matching queries are saved to `examples.json` with their timings. Add `--llm 8` to also ask Gemini for 8 harder, free-form questions, checked the same way.

## Keep it up to date when tables are added

```bash
graphkit watch --name SupplyChain   # exit code 3 = new items waiting for review
```

`watch` re-scans the source. Everything you approved stays exactly as it is. New tables and links are added to the draft marked **new** (orange in the UI), and stay there until you confirm them. Run it on a schedule with cron, or as a Cloud Run job with Cloud Scheduler, and alert on exit code 3.

## Use the graph from an agent

```python
from google.adk.agents import Agent
from graphkit.adk import graph_tools, prompt_snippet

agent = Agent(
    name="graph_analyst",
    model="gemini-3.5-flash",
    instruction="Answer with graph queries.\n" + prompt_snippet("graphkit_out/SupplyChain"),
    tools=graph_tools("graphkit_out/SupplyChain/approved.json"),
)
```

`prompt_snippet` gives the model the graph's shape plus your verified example queries from the benchmark. The query tool refuses anything that isn't a single read-only graph query, and returns at most 50 rows. The vehicle agent project uses the same pattern in `tools/supply_chain_graph.py`.

## See graphs in VS Code

There's no need for a custom extension. Google's `bigquery-magics` package draws graph results in any Jupyter notebook, and VS Code runs Jupyter notebooks. Open `notebooks/view_graph.ipynb` and follow the steps at the top. Queries must return whole paths with `RETURN TO_JSON(p)` to be drawn.

## Files it writes

`graphkit_out/<graph>/` holds:
- `scan.json`: what was read
- `draft.json`: what you're editing
- `approved.json`: the graph as last confirmed
- `notes.json`: what was skipped and why
- `terraform/`: `main.tf`, `versions.tf`, `graph.sql`
- `bench.json` and `examples.json`

Commit `approved.json` and `terraform/` to Git so graph changes go through review like code.

## Limits to know

- **Live cloud validation is workload-specific.** Graphs and semantic tables have been deployed through Terraform to BigQuery and Spanner using a copied freight dataset. See [the benchmark report](reports/cloud-benchmark-2026-10-19.md) for measured latency and correctness. Other schemas and workloads still need their own validation.
- BigQuery bills at least 10 MB per query, so a scan of a dataset with many guessed links costs a few cents. Sampling uses `list_rows`, which is free.
- Terraform can't delete a BigQuery job, so removing an edge from the graph means applying the smaller graph. To delete the whole graph, run `DROP PROPERTY GRAPH`.
- A junction table with more than two links becomes a node, and the edges go from it. Change that in the editor if you prefer.

## Tests

```bash
pip install -e ".[dev]"
pytest -q        # 25 tests, no cloud account needed
```

## Reviewed semantic dataset agents

GraphKit can now prepare a dataset-neutral semantic catalog and expose an agent
that generates SQL or GQL from questions. The graph is proposed before the agent
is configured. There are no fixed supply-chain entity names: manufacturers,
healthcare distributors, retailers and other industries can provide their own
schema descriptions, aliases and business definitions. Metadata does not create
business facts that are absent from the dataset.

See [REQUIREMENTS.md](REQUIREMENTS.md) for the implementation requirements.

### Prepare and approve

Install `pip install -e ".[bigquery,llm]"` (or `[spanner,llm]`). Configure the Google
Gen AI SDK for your chosen provider/project and model access. `GRAPHKIT_MODEL`
selects the generation model. Embedding commands require an explicit supported
embedding model so a model change cannot silently invalidate the index.

```bash
# First use the existing scan and review flow; edit graph nodes/edges in the UI.
graphkit scan --name Operations --backend bigquery --project P --dataset D
graphkit show --name Operations
graphkit confirm --name Operations

# Propose business metadata; omit --llm for metadata-only proposals.
graphkit semantic propose --name Operations --llm
# Review/edit graphkit_out/Operations/semantic.draft.json:
# change descriptions and aliases; keep id, kind, table, name and revision intact.
graphkit semantic approve --name Operations

# Use your provider's available embedding model identifier.
graphkit semantic embed --name Operations --embedding-model YOUR_EMBEDDING_MODEL

# Review graph.sql, semantic.sql, main.tf and semantic.tf before deployment.
graphkit apply --name Operations --plan
graphkit apply --name Operations
graphkit semantic publish --name Operations

graphkit ask --name Operations --embedding-model YOUR_EMBEDDING_MODEL \
  --question "Which vendors provide parts used in our products?" --mode auto
```

Semantic approval generates `semantic.sql` and `semantic.tf` beside the graph's
Terraform. They create a graph-specific `GraphkitSemantic_<hash>` table with
catalog IDs, descriptions, aliases, model IDs and `ARRAY<FLOAT64>` embeddings.
Publishing uses upserts keyed by catalog hash and item ID. It is separate from
Terraform and can be retried without duplicating rows in a single publishing
process. BigQuery publishing should not run concurrently: its table has no
uniqueness constraint. Old catalog versions remain; retention is operator-managed.
Generated metadata tables are excluded from later scans.

SQLite supports this flow without Terraform: publish creates its metadata table
and stores vectors as JSON. It still needs a model provider for live `ask`; tests
use injected providers and do not require cloud access.

### Create an agent in Python

```python
from graphkit.adk import dataset_tools
from graphkit.llm import _ask
from graphkit.graph.semantic_workflow import GeminiEmbeddings
from graphkit.workflow import Workspace

ws = Workspace("graphkit_out", "Operations")
embeddings = GeminiEmbeddings("YOUR_EMBEDDING_MODEL")

# Pass these tools to your existing ADK Agent.
tools = dataset_tools(
    ws,
    ask=_ask,
    embed_question=embeddings.question,
    embedding_model=embeddings.model,
)
```

For a direct service endpoint, construct `graphkit.agent.DatasetAgent` with the
same arguments and call `answer(question)`. Reuse its instance between requests.
Provider functions are injectable: `ask(prompt)` returns a JSON-compatible dict;
`embed_question(text)` returns a vector compatible with the catalog's model.

Each answer includes executed rows, SQL/GQL, catalog references, truncation and
retrieval/generation/execution/explanation timings. Unsupported questions can
return an abstention. SQL references are checked against scanned tables using
SQLGlot; GQL is limited to a single `GRAPH <approved graph> MATCH` query. SQLite
uses a read-only connection, Spanner a read-only snapshot, and BigQuery verifies
the server-parsed statement type with a dry run before execution. Use a separate
read-only serving identity scoped to the approved data; schema text and prompts
are not access controls. Cloud query execution has a 30-second timeout, and
SQLite has a 10-second VM progress deadline.

### Current implementation boundaries

- Supported sources remain BigQuery, Spanner GoogleSQL and SQLite. Another
  database needs an `Adapter`, including `run_readonly`, supplied to the Python
  scan/agent workflows. This does not claim automatic support for every database.
- Developers review semantic text in JSON; the existing browser UI edits the graph.
- Retrieval defaults to an in-memory cosine search over the local approved
  index. `BigQueryCatalogRetriever` optionally embeds questions through BigQuery
  ML and performs native exact `VECTOR_SEARCH` over a versioned cloud catalog.
  `SpannerCatalogRetriever` supports native exact cosine retrieval. Set
  `use_embeddings=False` on DatasetAgent for full approved-catalog context
  without embedding artifacts or question-embedding calls.
  Server-side ANN/index deployment is not implemented. Keep approved local
  artifacts with the serving deployment; scale retrieval independently when the
  catalog grows. See [BQML evaluation](scripts/README.md#bigquery-ml-catalog-evaluation).
- Retrieval expands selected tables and includes the full approved graph schema
  for join correctness. Large schemas will need bounded path expansion.
- Graph/schema changes require semantic proposal and approval again, followed by
  embedding regeneration. Restart serving instances to load a new approved version.
- The request path has two model calls (query generation and evidence explanation),
  without automatic repair loops. An explanation is model-generated; the returned
  query and rows provide auditable evidence, not a guarantee of correctness.
- Offline tests and an opt-in live freight benchmark cover the implementation.
  Validate answer quality and p50/p95 latency with your own workloads before
  deployment. Installing the package or running pytest creates no cloud resources.

Measure the complete agent path using a JSON array of representative questions:

```bash
graphkit agent-bench --name Operations --embedding-model YOUR_EMBEDDING_MODEL \
  --questions questions.json --repeat 3
```

This writes `agent_bench.json` with successful-response p50/p95/p99 latency,
stage timings, abstentions and errors. It is a sequential baseline, not a
concurrent-load test or an answer-correctness evaluation.


### Live cloud benchmark

The freight validation scripts in [scripts/README.md](scripts/README.md) prepare
matching BigQuery and Spanner copies of an existing dataset and independently
check complex agent answers. They are opt-in and create cloud resources only
when explicitly run. Detailed timings stay in `graphkit_out/cloud_validation/`;
aggregate findings are written to `reports/`.

The [Customers_data hourly pipeline](pipelines/customers_to_spanner/README.md)
uses native BigQuery exports, Cloud Workflows and Cloud Scheduler to upsert
13 tables into a separate Spanner serving database. Terraform provisions its
schema, service identities, scheduling and error monitoring.

The [BigQuery ML catalog evaluation](reports/bqml-customers-benchmark-2026-10-19.md)
generates schema embeddings directly in `Customers_data` and compares native
BigQuery vector retrieval with local retrieval over the same vectors, including
complete-answer correctness, latency and model-capacity failures.

The [matched retrieval comparison](scripts/README.md#matched-no-embeddingbigqueryspanner-comparison)
tests full-catalog context without embeddings against native BigQuery and
Spanner vector retrieval, using identical business data and document vectors.
The [four-way results](reports/retrieval-comparison-2026-10-19.md) and
[aggregate JSON baseline](reports/retrieval-comparison-2026-10-19.json) preserve
correctness, errors, stage timings and complex-question comparisons.

For fair measurements, set `use_query_cache: false` in a BigQuery graph's location
before creating its approved semantic revision. Serving otherwise defaults to
query caching. Metadata publishing batches up to 25 catalog objects per BigQuery
MERGE job.

## Code organization

Graph code lives in `graphkit/graph/`; chat code lives in `graphkit/chat/`.
React and tests use matching `graph/` and `chat/` folders.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the layout and updated import paths.

## Independent chat mode

Graph creation is the default; chat is disabled unless `CHAT_ENABLED=true`.
The conversational assistant can run without GraphKit workflows, graph tools,
semantic embeddings or Streamlit. See [chat-only setup and evaluations](CHAT.md).

## License

This project is licensed under the [MIT License](LICENSE).
