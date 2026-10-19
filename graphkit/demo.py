"""Build a small, made-up vehicle supply-chain dataset.

All names and numbers are invented. The data is consistent: a recall
affects exactly the models that use the recalled parts.

    graphkit demo                 # writes ./demo/supply_chain/*.csv and ./demo/supply_chain.db

The SQLite file declares no foreign keys on purpose, so the scan has to
find the links from names, descriptions and values, as it would in a
real warehouse without constraints.
"""
from __future__ import annotations

import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

COMPONENTS = ["BRAKES", "AIRBAGS", "ELECTRICAL", "STEERING", "FUEL SYSTEM", "SEAT BELTS"]

TABLES = {
    "suppliers": ("Companies that make parts. Made-up data.", [
        ("supplier_id", "TEXT", "Unique supplier code"),
        ("name", "TEXT", "Supplier company name"),
        ("country", "TEXT", "Country of the supplier's main factory"),
        ("tier", "INTEGER", "1 = ships straight to our plants, 2 = ships to tier-1 suppliers"),
    ]),
    "plants": ("Vehicle assembly plants.", [
        ("plant_id", "TEXT", "Unique plant code"),
        ("name", "TEXT", "Plant name"),
        ("country", "TEXT", "Country"),
    ]),
    "parts": ("Parts used to build vehicles.", [
        ("part_id", "TEXT", "Unique part number"),
        ("name", "TEXT", "Part name"),
        ("component", "TEXT", "Component group, matches the recall component"),
        ("supplier_id", "TEXT", "References suppliers: the company that makes this part"),
        ("unit_cost", "REAL", "Cost per part in USD"),
    ]),
    "vehicle_models": ("Vehicle models and model years.", [
        ("model_id", "TEXT", "Unique model code"),
        ("name", "TEXT", "Model name"),
        ("model_year", "INTEGER", "Model year"),
        ("body_type", "TEXT", "SUV, sedan, truck or van"),
        ("plant_id", "TEXT", "Plant that assembles this model"),
    ]),
    "part_usage": ("Which parts each vehicle model uses.", [
        ("part_id", "TEXT", "The part"),
        ("model_id", "TEXT", "The vehicle model that uses it"),
        ("qty_per_vehicle", "INTEGER", "How many of this part one vehicle needs"),
    ]),
    "recalls": ("Safety recall campaigns.", [
        ("recall_id", "TEXT", "Recall campaign number"),
        ("report_date", "TEXT", "Date the recall was filed"),
        ("component", "TEXT", "Component group with the defect"),
        ("severity", "TEXT", "LOW, MEDIUM or HIGH"),
        ("summary", "TEXT", "What is wrong"),
    ]),
    "recall_parts": ("Parts named in each recall.", [
        ("recall_id", "TEXT", "The recall"),
        ("part_id", "TEXT", "A recalled part"),
    ]),
    "recall_models": ("Vehicle models covered by each recall.", [
        ("recall_id", "TEXT", "The recall"),
        ("model_id", "TEXT", "An affected vehicle model"),
    ]),
    "shipments": ("Part shipments from suppliers to plants.", [
        ("shipment_id", "TEXT", "Unique shipment number"),
        ("supplier_code", "TEXT", "Who shipped it"),  # odd name on purpose: found by values
        ("plant_id", "TEXT", "Plant that received it"),
        ("ship_date", "TEXT", "Date shipped"),
        ("units", "INTEGER", "Number of parts in the shipment"),
    ]),
}


def build(seed: int = 7) -> dict[str, list[dict]]:
    rnd = random.Random(seed)
    suppliers = [
        {"supplier_id": f"S{i:03d}", "name": n, "country": c, "tier": t}
        for i, (n, c, t) in enumerate([
            ("Northstar Brakes", "USA", 1), ("Halden Safety Systems", "Germany", 1),
            ("Kirin Electrics", "Japan", 1), ("Sierra Steering Co", "Mexico", 1),
            ("Bluewater Fuel Tech", "USA", 2), ("Arcadia Restraints", "India", 2),
            ("Mapleline Components", "Canada", 2), ("Orion Wiring", "China", 2),
        ], 1)
    ]
    makes = {"BRAKES": ["S001", "S007"], "AIRBAGS": ["S002", "S006"], "ELECTRICAL": ["S003", "S008"],
             "STEERING": ["S004", "S007"], "FUEL SYSTEM": ["S005"], "SEAT BELTS": ["S006", "S002"]}
    names = {"BRAKES": ["brake caliper", "brake pad set", "ABS module", "brake line"],
             "AIRBAGS": ["driver airbag", "curtain airbag", "airbag inflator"],
             "ELECTRICAL": ["wiring harness", "body control module", "battery sensor", "fuse box"],
             "STEERING": ["steering rack", "tie rod", "power steering pump"],
             "FUEL SYSTEM": ["fuel pump", "fuel injector", "fuel tank strap"],
             "SEAT BELTS": ["seat belt retractor", "buckle assembly", "pretensioner"]}
    parts, n = [], 1
    for comp, ps in names.items():
        for p in ps:
            for sup in makes[comp]:
                parts.append({"part_id": f"P{n:04d}", "name": p, "component": comp, "supplier_id": sup,
                              "unit_cost": round(rnd.uniform(4, 380), 2)})
                n += 1
    plants = [{"plant_id": f"PL{i}", "name": nm, "country": c} for i, (nm, c) in enumerate([
        ("Lakeside Assembly", "USA"), ("Ridgeview Truck Plant", "USA"),
        ("Valle Assembly", "Mexico"), ("Chennai East Assembly", "India")], 1)]
    models = []
    for i, (nm, body) in enumerate([("Atlas", "SUV"), ("Comet", "sedan"), ("Granite", "truck"),
                                     ("Harbor", "van"), ("Ember", "SUV")], 1):
        for year in (2024, 2025):
            models.append({"model_id": f"M{i}{year % 100}", "name": nm, "model_year": year, "body_type": body,
                           "plant_id": f"PL{(i % 4) + 1}"})
    usage = []
    for m in models:
        for comp in COMPONENTS:
            options = [p for p in parts if p["component"] == comp]
            for p in rnd.sample(options, k=min(len(options), rnd.randint(2, 3))):
                usage.append({"part_id": p["part_id"], "model_id": m["model_id"], "qty_per_vehicle": rnd.randint(1, 4)})
    recalls, recall_parts, recall_models = [], [], []
    for i in range(1, 13):
        comp = rnd.choice(COMPONENTS)
        bad = rnd.sample([p for p in parts if p["component"] == comp], k=rnd.randint(1, 2))
        rid = f"RC-{2024 + i % 2}-{i:03d}"
        recalls.append({"recall_id": rid, "report_date": f"{2024 + i % 2}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                        "component": comp, "severity": rnd.choice(["LOW", "MEDIUM", "HIGH"]),
                        "summary": f"{bad[0]['name'].capitalize()} may fail. Made-up recall for practice."})
        affected = set()
        for p in bad:
            recall_parts.append({"recall_id": rid, "part_id": p["part_id"]})
            affected |= {u["model_id"] for u in usage if u["part_id"] == p["part_id"]}
        recall_models += [{"recall_id": rid, "model_id": m} for m in sorted(affected)]
    shipments = []
    for i in range(1, 61):
        shipments.append({"shipment_id": f"SH{i:05d}", "supplier_code": rnd.choice(suppliers)["supplier_id"],
                          "plant_id": rnd.choice(plants)["plant_id"],
                          "ship_date": f"2025-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
                          "units": rnd.randint(50, 2000)})
    return {"suppliers": suppliers, "plants": plants, "parts": parts, "vehicle_models": models,
            "part_usage": usage, "recalls": recalls, "recall_parts": recall_parts,
            "recall_models": recall_models, "shipments": shipments}


def write_csv(data, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for table, rows in data.items():
        with open(out_dir / f"{table}.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[c[0] for c in TABLES[table][1]])
            w.writeheader()
            w.writerows(rows)
    descriptions = {t: {"": d, **{c[0]: c[2] for c in cols}} for t, (d, cols) in TABLES.items()}
    (out_dir / "descriptions.json").write_text(json.dumps(descriptions, indent=2) + "\n")


def write_sqlite(data, path: Path, tables: list[str] | None = None):
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    keys = {"suppliers": "supplier_id", "plants": "plant_id", "parts": "part_id",
            "vehicle_models": "model_id", "recalls": "recall_id", "shipments": "shipment_id"}
    con.execute("CREATE TABLE _descriptions (table_name TEXT, column_name TEXT, description TEXT)")
    for table in tables or list(data):
        desc, cols = TABLES[table]
        defs = ", ".join(f"{c} {t}{' PRIMARY KEY' if keys.get(table) == c else ''}" for c, t, _ in cols)
        con.execute(f"CREATE TABLE {table} ({defs})")
        names = [c[0] for c in cols]
        con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(names))})",
                        [[r[n] for n in names] for r in data[table]])
        con.execute("INSERT INTO _descriptions VALUES (?, '', ?)", (table, desc))
        con.executemany("INSERT INTO _descriptions VALUES (?, ?, ?)", [(table, c, d) for c, _, d in cols])
    con.commit()
    con.close()


def make(out_dir: str | Path = "demo", tables: list[str] | None = None) -> Path:
    """Write the CSVs and the SQLite file. Returns the SQLite path."""
    out = Path(out_dir)
    data = build()
    write_csv(data, out / "supply_chain")
    db = out / "supply_chain.db"
    write_sqlite(data, db, tables)
    return db


if __name__ == "__main__":
    print(f"Wrote {make(sys.argv[1] if len(sys.argv) > 1 else 'demo')}")
