import pytest

from graphkit.graph.adapters import open_adapter
from graphkit.graph.adapters import scan
from graphkit.graph.core.demo import make
from graphkit.graph.core.infer import infer


@pytest.fixture
def demo_db(tmp_path):
    return make(tmp_path / "demo")


@pytest.fixture
def demo(demo_db):
    """(adapter, scanned tables, inferred spec) for the made-up supply chain."""
    adapter = open_adapter("sqlite", {"path": str(demo_db)})
    tables = scan(adapter, sample_rows=100)
    spec = infer(tables, adapter, name="SupplyChain", backend="sqlite", location={"path": str(demo_db)}).spec
    return adapter, tables, spec
