"""Backward-compatible shim: `graphkit.adk` moved to `graphkit.graph.agents.tools`
during the enterprise-folder reorg. Kept because the README documents
`from graphkit.adk import graph_tools, prompt_snippet` as this project's public
API for other projects wiring graphkit into their own Google ADK agent.
"""
from graphkit.graph.agents.tools import describe
from graphkit.graph.agents.tools import graph_tools
from graphkit.graph.agents.tools import is_read_only_graph_query
from graphkit.graph.agents.tools import prompt_snippet
from graphkit.graph.agents.tools import query_parts
