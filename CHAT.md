# Standalone chat and optional GraphKit integration

Graph creation is the default. Chat is disabled unless `CHAT_ENABLED=true`.
Chat is a separate runtime. Streamlit remains the GraphKit workflow/editor UI;
it is not required for chat. React supports both modes, selected by the backend.

| Concern | Standalone chat | Optional GraphKit integration |
| --- | --- | --- |
| Agent | `graphkit/chat/agent.py` | `graphkit/graph/agents/dataset_agent.py`, `chat_tools.py` |
| Guardrails | `graphkit/chat/guardrails.py`: Model Armor input/output screening | `graphkit/graph/agents/dataset_guardrails.py`: read-only queries and approved-source scope |
| Evaluations | `graphkit/chat/eval.py` | `graphkit/graph/benchmarking/chat_integration.py`, existing graph/dataset benchmarks |
| UI | React assistant, model selection, history, attachments | React graph editor or separately launched Streamlit editor |

Disabling GraphKit does not disable chat content guardrails. Graph query checks
remain mandatory whenever dataset tools are enabled. Chat imports now use `graphkit.chat.agent` and `graphkit.chat.guardrails`.
Graph imports use the `graphkit.graph` namespace.

## Run only chat

```sh
pip install -e '.[api,chat]'
python -m graphkit.chat serve --port 8765
```

After installing, `graphkit-chat serve` is equivalent. Neither command imports
graph workflows, adapters, graph benchmarks, dataset tools or embedding clients.
No approved graph, semantic catalog or embedding model is required.

To serve an existing React production build with an explicit ASGI command:

```sh
GRAPHKIT_ENABLED=false CHAT_ENABLED=true uvicorn graphkit.api.application:app --host 0.0.0.0 --port 8080
```

`/api/capabilities` reports the mode. React opens directly into chat and does not
download its graph workflow bundle. Graph APIs are absent and return 404.
`GRAPHKIT_ENABLED=true` (the default) enables graph creation. Set `CHAT_ENABLED=true` as well to enable the
assistant and GraphKit chat tools. Both flags false is an invalid configuration. Restart the process after changing the mode. Use
`graphkit.api.application:app` for configurable startup; the graph-specific
`graphkit.graph.api:app` entrypoint remains the graph-enabled application.

## Chat-only container

First build React with the public Firebase browser configuration in
`graphkit-web/.env.local`:

```sh
cd graphkit-web
npm ci
npm run build
cd ..
docker build -f Dockerfile.chat -t graphkit-chat .
```

`Dockerfile.chat` copies only chat, authentication, configuration and web-serving
Python modules. It excludes the GraphKit backend, Streamlit, graph adapters,
graph benchmarks and the demo database. The default `Dockerfile` still includes
the full application. On Cloud Run, either deploy the chat-only image or set
`GRAPHKIT_ENABLED=false` on an image built from the updated default Dockerfile.

## Configuration

Chat still needs its own services and credentials:

- `GOOGLE_CLOUD_PROJECT` and the generation provider/Vertex AI configuration.
- Firebase Authentication, browser `VITE_FIREBASE_*` build settings and an
  authorized browser hostname.
- Firestore for per-user conversation history and the corresponding runtime IAM
  access. In-memory ADK conversation context resets on process restart.
- Model Armor access and a content-screening template. Configure
  `CHAT_MODEL_ARMOR_LOCATION` and `CHAT_MODEL_ARMOR_TEMPLATE` independently of
  graph query checks. Legacy `MODEL_ARMOR_*` variables remain fallback settings.
- Optional `CHAT_MODEL` for the default generation model.

Graph storage mounts, BigQuery/Spanner access and embedding configuration are
unnecessary in chat-only mode. Keep Cloud Run access controls independent of
the application's Firebase user sign-in, as described in [DEPLOYMENT.md](DEPLOYMENT.md).

## Separate evaluations

Standalone conversation and content-guardrail evaluations (live model calls):

```sh
python -m graphkit.chat eval --model gemini-3.5-flash
```

Graph-integrated chat routing evaluations (requires approved dataset and embeddings):

```sh
graphkit chat-eval --name SupplyChain --embedding-model gemini-embedding-001
```

Graph query correctness/performance benchmarks remain under
`graphkit/graph/benchmarking`, including the existing `graphkit agent-bench` command.
Live content-guardrail evaluations use the configured Model Armor policy; they
are distinct from offline regression tests.

```sh
python -m pytest tests/chat/test_chat_standalone.py tests/chat/test_chat_api.py tests/chat/test_model_armor.py -q
python -m pytest tests/graph/test_semantic_agent.py tests/graph/test_queries_bench.py -q
```

The standalone regression tests also recreate the chat-only container's Python
file layout and verify it works with graph modules physically absent.
