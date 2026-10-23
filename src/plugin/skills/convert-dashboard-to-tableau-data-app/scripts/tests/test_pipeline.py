"""
End to end through the Hyper API: files -> build_hyper.py (with a transform) ->
profile_hyper.py -> generate_tds.py. Skipped when tableauhyperapi isn't installed.
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("tableauhyperapi")
pytest.importorskip("pyarrow")

SCRIPTS = Path(__file__).resolve().parents[1]


def run(script, *args):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_flat_csv_to_related_tdsx(tmp_path):
    (tmp_path / "sales.csv").write_text(
        "order_id,customer,region,amount\n1,acme,AMER,10.5\n2,acme,AMER,4\n3,globex,EMEA,7.25\n4,,EMEA,1\n")
    (tmp_path / "split.sql").write_text(
        "CREATE TABLE public.orders AS SELECT order_id, customer, amount FROM staging.sales;\n"
        "CREATE TABLE public.customers AS SELECT DISTINCT customer, region FROM staging.sales "
        "WHERE customer IS NOT NULL;\n")
    hyper = tmp_path / "sales.hyper"
    out = run("build_hyper.py", hyper, f"sales={tmp_path / 'sales.csv'}", "--transform", tmp_path / "split.sql")
    assert "public.orders: 4 rows" in out and "public.customers: 2 rows" in out
    assert "staging" not in out

    model_path = tmp_path / "model.json"
    profile = json.loads(run("profile_hyper.py", hyper, "--model-out", model_path,
                             "--check", "orders.customer=customers.customer"))
    check = profile["checks"][0]
    assert check["toUnique"] and check["fromNullKeys"] == 1 and check["fromOrphans"] == 0
    assert profile["relationshipCandidates"] == [
        {"from": {"table": "orders", "column": "customer"}, "to": {"table": "customers", "column": "customer"}}]

    model = json.loads(model_path.read_text())
    assert [t["name"] for t in model["tables"]] == ["orders", "customers"]
    model["caption"] = "Sales"
    model_path.write_text(json.dumps(model))
    tdsx, fields = tmp_path / "Sales.tdsx", tmp_path / "fields.json"
    run("generate_tds.py", hyper, model_path, "--out", tdsx, "--fields-out", fields)
    with zipfile.ZipFile(tdsx) as z:
        assert sorted(z.namelist()) == ["Data/Extracts/sales.hyper", "Sales.tds"]
        assert "<relationship>" in z.read("Sales.tds").decode()
    names = {f["name"] for f in json.loads(fields.read_text())}
    assert {"Order ID", "Customer", "Customer (Customers)", "Amount", "Region"} == names
