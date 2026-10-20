# Project layout

Graph creation is the default. Chat remains off unless `CHAT_ENABLED=true`.

```text
graphkit/
  graph/                 Graph implementation
    core/                Scan, infer, review, model, DDL, Terraform
    adapters/            BigQuery, Spanner, SQLite
    semantic/            Catalog, embeddings, retrieval
    agents/              Dataset agent, query guardrails, graph tools
    benchmarking/        Graph evaluations and chat-tool integration cases
    ui/                  Streamlit graph editor and visualization asset
    api.py               Graph HTTP endpoints
    cli.py               Graph CLI
    chat_integration.py  Optional bridge for chat to use a graph workspace
  chat/                  Conversational assistant implementation
    agent.py             ADK orchestration
    api.py               Chat HTTP endpoints
    auth.py              Firebase user verification
    store.py             Conversation persistence
    guardrails.py        Chat content screening
    eval.py              Standalone chat evaluations
    __main__.py          Chat server/evaluation CLI
  shared/                Feature flags and model metadata
  api/application.py     Selects graph-only, chat-only, or combined web mode
  adk.py                 Stable public graph-tool import facade
  cli.py                 Compatibility facade for existing CLI installs

graphkit-web/src/
  graph/                 Graph React app, components, API client, types
  chat/                  Chat React app, components, API client, Firebase, types
  shared/                HTTP helper, capabilities, model metadata types
  App.tsx                Chooses the feature app from backend capabilities

tests/
  graph/                 Graph workflow, agent, adapter and Streamlit tests
  chat/                  Chat API, isolation and content-guardrail tests
```

Graph query guardrails live with the graph agent. Chat content guardrails live
with the chat agent. The optional graph/chat bridge is loaded only when both
features are enabled. Chat-only tests also run with the entire graph package
physically absent. Graph-only startup does not import chat or ADK.

## Imports

Use the new canonical namespaces:

```python
from graphkit.graph.core.workflow import Workspace, do_scan
from graphkit.graph.agents.dataset_agent import DatasetAgent
from graphkit.chat.agent import build_agent
```

The former `graphkit.core`, `graphkit.agents`, `graphkit.semantic`,
`graphkit.adapters`, `graphkit.benchmarking` and `graphkit.ui` implementations
now live under `graphkit.graph`. Chat HTTP/auth code moved from `graphkit.api`
to `graphkit.chat`. Update imports in external projects that used those internal
paths. Public imports from `graphkit.adk` and `from graphkit import Node,
Edge, GraphSpec` still work.

The configurable server entrypoint stays `graphkit.api.application:app`.
The graph-specific entrypoint is now `graphkit.graph.api:app`.
CLI commands remain `graphkit` and `graphkit-chat` after installation.
See [CHAT.md](CHAT.md) and [DEPLOYMENT.md](DEPLOYMENT.md) for startup options.
