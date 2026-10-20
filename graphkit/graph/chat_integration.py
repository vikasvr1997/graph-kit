"""Optional bridge from chat to approved GraphKit workspaces and embedding tools."""
import functools
import os
from pathlib import Path

from graphkit.chat.agent import get_runner
from graphkit.graph.core.workflow import Workspace
from graphkit.graph.agents.llm import _ask
from graphkit.graph.semantic.workflow import GeminiEmbeddings


def get_runner_for_workspace(name, generation_model, embedding_model):
    workspace = Workspace(Path(os.getenv("GRAPHKIT_HOME", "graphkit_out")), name)
    ask = functools.partial(_ask, model=generation_model)
    embed_question = GeminiEmbeddings(embedding_model).question
    return get_runner(workspace, ask, embed_question, embedding_model, generation_model)
