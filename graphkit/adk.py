"""Backward-compatible shim: `graphkit.adk` moved to `graphkit.agents.tools`
during the enterprise-folder reorg. Kept because the README documents
`from graphkit.adk import graph_tools, prompt_snippet` as this project's public
API for other projects wiring graphkit into their own Google ADK agent.
"""
from .agents.tools import (  # noqa: F401
    describe, graph_tools, is_read_only_graph_query, prompt_snippet, query_parts,
)
