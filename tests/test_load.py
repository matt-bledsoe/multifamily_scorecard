import duckdb
import pytest

from mf_scorecard.data.load import RAW_TABLE, column_types, load_raw, read_schema


def write_csv(path, header, rows=()):
    lines = [",".join(header), *(",".join(r) for r in rows)]
    path.write_text("\n".join(lines) + "\n")


def test_schema_is_well_formed():
    schema = read_schema()
    assert schema["fnma_name"].is_unique().all()
    assert schema["name"].is_unique().all()
    assert schema["type"].null_count() == 0


def test_schema_dtypes_are_polars_types():
    import polars as pl

    bad = [d for d in schema_dtypes() if not hasattr(pl, d)]
    assert not bad, f"Not polars dtypes: {bad}"


def schema_dtypes():
    return read_schema()["dtype"].unique().to_list()


def test_header_mismatch_raises(tmp_path):
    f = tmp_path / "bad.csv"
    write_csv(f, ["Loan Number", "Not A Real Column"])
    with pytest.raises(ValueError, match="Not A Real Column"):
        column_types(f, read_schema())


def test_load_roundtrip(tmp_path):
    schema = read_schema()
    header = list(reversed(schema["fnma_name"]))  # order must follow the file
    f = tmp_path / "ok.csv"
    write_csv(f, header, [[""] * len(header)])
    db = tmp_path / "test.duckdb"
    load_raw(f, db)
    with duckdb.connect(str(db)) as con:
        cols = [r[0] for r in con.execute(f"DESCRIBE {RAW_TABLE}").fetchall()]
        n = con.execute(f"SELECT count(*) FROM {RAW_TABLE}").fetchone()[0]
    assert cols[0] == schema["name"][-1]
    assert n == 1
