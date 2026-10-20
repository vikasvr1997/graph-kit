"""GraphKit workflows and an independently runnable chat assistant."""
__version__ = "0.1.0"
__all__ = ["Edge", "GraphSpec", "Node", "__version__"]


def __getattr__(name):
    if name in {"Edge", "GraphSpec", "Node"}:
        from .core import model
        return getattr(model, name)
    raise AttributeError(name)
