"""Type normalization and Trino row batching for export_query.py (needs pyarrow)."""

import decimal

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

import export_query as eq  # noqa: E402


@pytest.mark.parametrize("arrow, expected", [
    (pa.decimal128(38, 0), pa.int64()),
    (pa.decimal128(38, 4), pa.float64()),
    (pa.decimal128(10, 2), pa.decimal128(10, 2)),
    (pa.time64("us"), pa.string()),
    (pa.large_string(), pa.string()),
    (pa.dictionary(pa.int32(), pa.string()), pa.string()),
    (pa.timestamp("us", tz="UTC"), pa.timestamp("us", tz="UTC")),
])
def test_normalize_type(arrow, expected):
    assert eq.normalize_type("c", arrow) == expected


@pytest.mark.parametrize("arrow", [pa.binary(), pa.list_(pa.int32()), pa.struct([("a", pa.int32())])])
def test_unsupported_types_fail_with_hint(arrow, capsys):
    with pytest.raises(SystemExit):
        eq.normalize_type("c", arrow)
    assert "cast it to a string or flatten it" in capsys.readouterr().err


@pytest.mark.parametrize("code, expected", [
    ("bigint", pa.int64()), ("varchar(20)", pa.string()), ("decimal(12,3)", pa.decimal128(12, 3)),
    ("timestamp(3)", pa.timestamp("us")), ("timestamp(6) with time zone", pa.timestamp("us", tz="UTC")),
    ("time(3)", pa.string()), ("array(varchar)", pa.binary()), ("boolean", pa.bool_()),
])
def test_trino_arrow_type(code, expected):
    assert eq.trino_arrow_type(code) == expected


class FakeCursor:
    def __init__(self, description, rows):
        self.description, self._rows = description, list(rows)

    def fetchmany(self, n):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out


def test_trino_batches_stream_into_parquet(tmp_path):
    desc = [("id", "bigint"), ("amount", "decimal(38,0)"), ("name", "varchar"), ("t", "time(3)")]
    rows = [(i, decimal.Decimal(i * 10), None if i % 2 else f"n{i}", f"10:00:0{i % 10}") for i in range(25)]
    sink = eq.Sink(tmp_path / "out.parquet")
    batches = list(eq.trino_batches(FakeCursor(desc, rows), size=10))
    assert [b.num_rows for b in batches] == [10, 10, 5]
    for b in batches:
        sink.write(b)
    result = sink.close()
    assert result["rows"] == 25
    assert result["columns"] == [["id", "int64"], ["amount", "int64"], ["name", "string"], ["t", "string"]]
    table = pq.read_table(tmp_path / "out.parquet")
    assert table.column("amount").to_pylist()[:3] == [0, 10, 20]


def test_trino_empty_result_keeps_schema(tmp_path):
    sink = eq.Sink(tmp_path / "out.parquet")
    for b in eq.trino_batches(FakeCursor([("id", "bigint")], []), size=10):
        sink.write(b)
    assert sink.close() == {"out": str((tmp_path / "out.parquet").resolve()), "rows": 0,
                            "columns": [["id", "int64"]]}


def test_duplicate_column_names_rejected(tmp_path, capsys):
    sink = eq.Sink(tmp_path / "out.parquet")
    with pytest.raises(SystemExit):
        sink.write(pa.table([pa.array([1]), pa.array([2])], names=["id", "id"]))
    assert "duplicate column names ['id']" in capsys.readouterr().err
