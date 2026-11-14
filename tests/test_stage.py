import duckdb
import pytest

from mf_scorecard.data.load import RAW_TABLE, read_schema
from mf_scorecard.data.stage import STAGE_TABLE, build_stage


@pytest.fixture
def con():
    """In-memory DB with an empty raw table that has the schema's raw types."""
    con = duckdb.connect()
    cols = ", ".join(
        f'"{r["name"]}" {r["type"]}' for r in read_schema().iter_rows(named=True)
    )
    con.execute(f"CREATE TABLE {RAW_TABLE} ({cols})")
    yield con
    con.close()


def stage_values(con, column, values):
    """Insert raw values into one column, stage, and return staged values."""
    for v in values:
        con.execute(f'INSERT INTO {RAW_TABLE} ("{column}") VALUES (?)', [v])
    build_stage(con)
    return [
        r[0] for r in con.execute(f'SELECT "{column}" FROM {STAGE_TABLE}').fetchall()
    ]


def test_currency(con):
    got = stage_values(
        con,
        "lifetime_net_credit_loss_amount",
        ["$1,318,307.79", "($284,973.37)", "$0.00", None],
    )
    assert got == [1318307.79, -284973.37, 0.0, None]


def test_flags(con):
    assert stage_values(con, "sdq_indicator", ["Y", "N", None]) == [True, False, None]


def test_unexpected_flag_raises(con):
    with pytest.raises(duckdb.Error, match="Unexpected sdq_indicator"):
        stage_values(con, "sdq_indicator", ["Yes"])


def test_year_built_placeholder(con):
    got = stage_values(con, "year_built", ["1985", "Multiple Properties", None])
    assert got == [1985, None, None]


def test_unparseable_currency_raises(con):
    with pytest.raises(duckdb.Error):
        stage_values(con, "upb_current", ["N/A"])


def test_staged_types_follow_schema(con):
    build_stage(con)
    staged = dict(
        con.execute(
            f"SELECT column_name, column_type FROM (DESCRIBE {STAGE_TABLE})"
        ).fetchall()
    )
    expected = {"Float64": "DOUBLE", "Int64": "INTEGER", "Boolean": "BOOLEAN"}
    for r in read_schema().iter_rows(named=True):
        if r["type"] == "VARCHAR" and r["dtype"] in expected:
            assert staged[r["name"]] == expected[r["dtype"]], r["name"]
