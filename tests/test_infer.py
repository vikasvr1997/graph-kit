import sqlite3

from graphkit import workflow
from graphkit.adapters import open_adapter, scan
from graphkit.infer import infer, node_label, singular


def edges_by_label(spec):
    return {e.label: e for e in spec.edges}


def test_naming():
    assert singular("vehicle_models") == "vehicle_model"
    assert singular("addresses") == "address"
    assert singular("categories") == "category"
    assert node_label("vehicle_models") == "VehicleModel"


def test_finds_nodes_and_junction_edges(demo):
    _, _, spec = demo
    assert {n.label for n in spec.nodes} == {"Part", "Plant", "Recall", "Supplier", "VehicleModel"}
    e = edges_by_label(spec)
    # Junction tables become edges, read in column order.
    assert (e["PART_USAGE"].source, e["PART_USAGE"].dest) == ("Part", "VehicleModel")
    assert e["PART_USAGE"].key == ["part_id", "model_id"]
    assert (e["RECALL_PARTS"].source, e["RECALL_PARTS"].dest) == ("Recall", "Part")
    # A foreign-key column in a node table becomes an edge on that table.
    assert e["HAS_SUPPLIER"].table == "parts"
    assert e["HAS_SUPPLIER"].dest_key == ["supplier_id"]
    assert "description" in e["HAS_SUPPLIER"].reason
    assert spec.validate() == []


def test_value_only_link_found_with_low_confidence(demo):
    _, _, spec = demo
    ship = edges_by_label(spec)["SHIPMENTS"]
    # supplier_code doesn't match any key name; the sampled values gave it away.
    assert ship.source_key == ["supplier_code"] and ship.source == "Supplier"
    assert ship.confidence == 0.5


def test_wrong_values_reject_a_name_match(tmp_path):
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE owners (owner_id TEXT PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE cars (car_id TEXT PRIMARY KEY, owner_id TEXT)")
    con.executemany("INSERT INTO owners VALUES (?, ?)", [("O1", "a"), ("O2", "b")])
    con.executemany("INSERT INTO cars VALUES (?, ?)", [("C1", "X9"), ("C2", "X8")])
    con.commit()
    a = open_adapter("sqlite", {"path": str(db)})
    spec = infer(scan(a), a, name="G", backend="sqlite", location={}).spec
    assert spec.edges == []  # name fits, values don't


def test_declared_foreign_key_wins(tmp_path):
    db = tmp_path / "fk.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE teams (code TEXT PRIMARY KEY)")
    con.execute("CREATE TABLE players (pid INTEGER PRIMARY KEY, club TEXT REFERENCES teams(code))")
    con.execute("INSERT INTO teams VALUES ('T1')")
    con.execute("INSERT INTO players VALUES (1, 'T1')")
    con.commit()
    a = open_adapter("sqlite", {"path": str(db)})
    spec = infer(scan(a), a, name="G", backend="sqlite", location={}).spec
    (e,) = spec.edges
    assert (e.source, e.dest, e.dest_key, e.confidence) == ("Player", "Team", ["club"], 1.0)


def test_watch_adds_new_tables_without_touching_approved(tmp_path, demo_db):
    ws = workflow.Workspace(tmp_path / "out", "SupplyChain")
    spec, _ = workflow.do_scan(ws, "sqlite", {"path": str(demo_db)})
    spec.edges[0].label = "USED_IN"  # a developer renamed it before approving
    workflow.confirm(ws, spec)

    con = sqlite3.connect(demo_db)
    con.execute("CREATE TABLE warranty_claims (claim_id TEXT PRIMARY KEY, model_id TEXT, part_id TEXT, amount REAL)")
    con.executemany("INSERT INTO warranty_claims VALUES (?, ?, ?, ?)", [("W1", "M124", "P0001", 5.0), ("W2", "M125", "P0002", 7.5)])
    con.commit()

    new = workflow.do_watch(ws)
    assert new == ["WARRANTY_CLAIMS"]
    draft = ws.draft()
    assert "USED_IN" in {e.label for e in draft.edges}  # approved rename kept
    assert workflow.pending_changes(ws)["added"] == ["edge:WARRANTY_CLAIMS"]
    assert workflow.do_watch(ws) == ["WARRANTY_CLAIMS"]  # still waiting until confirmed
