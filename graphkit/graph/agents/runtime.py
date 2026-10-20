"""Lazy construction keeps ADK optional for graph creation and schema review."""
import os


def dataset_engine():
    value = os.getenv('GRAPHKIT_DATASET_ENGINE', 'adk').strip().lower()
    if value != 'adk':
        raise ValueError('Only the adk dataset engine is supported; remove GRAPHKIT_DATASET_ENGINE.')
    return value


def create_dataset_agent(workspace, embed_question=None, embedding_model=None,
                         adapter=None, *, generation_model='gemini-3.5-flash', **kwargs):
    dataset_engine()
    from .dataset_agent import DatasetAgent
    return DatasetAgent(workspace, embed_question=embed_question, embedding_model=embedding_model,
                        adapter=adapter, generation_model=generation_model, **kwargs)
