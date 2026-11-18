"""Runs the ViewDefinitions over the synthetic dataset, loads the tables into DuckDB, runs the four
SQL queries and checks each against an answer worked out directly from the resources.
Run: python test_queries.py"""
import duckdb
import fhirpathpy

from dataset import RESOURCES
from view_runner import run_view
from views import ALL_VIEWS

con = duckdb.connect()
for view in ALL_VIEWS:
    rows = run_view(view, RESOURCES)
    columns = list(rows[0])
    con.execute(f"CREATE TABLE {view['name']} AS SELECT * FROM (VALUES "
                + ", ".join("(" + ", ".join("?" for _ in columns) + ")" for _ in rows)
                + f") AS t({', '.join(columns)})", [row[c] for row in rows for c in columns])
    print(f"{view['name']:24} {len(rows):>3} rows  {columns}")

assert con.execute("SELECT count(*) FROM bp_readings").fetchone()[0] == 7
assert con.execute("SELECT count(*) FROM lab_results").fetchone()[0] == 8
assert con.execute("SELECT count(*) FROM observation_components").fetchone()[0] == 14     # 7 readings x 2 components

statements = [s.strip() for s in open("queries.sql", encoding="utf-8").read().split(";") if s.strip()]
results = {s.splitlines()[0][3:5]: con.execute(s).fetchall() for s in statements}
for name, rows in results.items():
    print(name, "->", rows)

# ---- answers worked out directly from the resources, independent of the views and the SQL
by_type = lambda t: [r for r in RESOURCES if r["resourceType"] == t]
pid = lambda r: r["subject"]["reference"].split("/")[1]
comp = lambda o, code: next(c["valueQuantity"]["value"] for c in o["component"] if c["code"]["coding"][0]["code"] == code)
bps = [o for o in by_type("Observation") if o["code"]["coding"][0]["code"] == "85354-9"]
a1cs = [o for o in by_type("Observation") if o["code"]["coding"][0]["code"] == "4548-4"]
latest = lambda obs: {p: max((o for o in obs if pid(o) == p), key=lambda o: o["effectiveDateTime"]) for p in {pid(o) for o in obs}}

l = latest(bps)
assert results["Q1"] == [(l["p1"]["effectiveDateTime"], 142, 88)]
assert results["Q2"] == sorted((p, comp(o, "8480-6"), o["effectiveDateTime"]) for p, o in l.items() if comp(o, "8480-6") >= 140)
assert results["Q2"] == [("p1", 142, "2026-11-03T09:42:00Z"), ("p4", 161, "2026-10-30T16:20:00Z")]
assert [float(v) for _, v in results["Q3"]] == [8.1, 7.9, 7.7]
on_metformin = {pid(m) for m in by_type("MedicationRequest")
                if m["status"] == "active" and m["medicationCodeableConcept"]["coding"][0]["code"] == "MED-0001"}
expected_q4 = sorted(p for p, o in latest(a1cs).items() if o["valueQuantity"]["value"] > 7.5 and p in on_metformin)
assert [r[0] for r in results["Q4"]] == expected_q4 == ["p1", "p5"]
print(f"duckdb {duckdb.__version__}, fhirpathpy {fhirpathpy.__version__ if hasattr(fhirpathpy, '__version__') else ''}")
print("ALL QUERY TESTS OK")
