"""Select the ADK dataset runtime or the original comparison baseline."""
import os


def dataset_engine():
    value = os.getenv('GRAPHKIT_DATASET_ENGINE', 'adk').strip().lower()
    if value not in {'adk', 'legacy'}:
        raise ValueError('GRAPHKIT_DATASET_ENGINE must be adk or legacy.')
    return value


def create_dataset_agent(workspace, ask=None, embed_question=None, embedding_model=None,
                         adapter=None, *, generation_model='gemini-3.5-flash', **kwargs):
    if dataset_engine() == 'adk':
        from .adk_dataset import AdkDatasetAgent
        return AdkDatasetAgent(workspace, embed_question, embedding_model, adapter=adapter,
                               generation_model=generation_model, **kwargs)
    from .dataset_agent import DatasetAgent
    if ask is None:
        import functools
        from .llm import _ask
        ask = functools.partial(_ask, model=generation_model)
    return DatasetAgent(workspace, ask, embed_question, embedding_model, adapter, **kwargs)
