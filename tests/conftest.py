import duckdb
import pytest

from mf_scorecard.data.load import read_schema
from mf_scorecard.data.stage import STAGE_TABLE

STAGED_TYPES = {"Float64": "DOUBLE", "Int64": "INTEGER", "Boolean": "BOOLEAN"}


@pytest.fixture
def stage_con():
    """In-memory DB with an empty stage table typed like the real one."""
    con = duckdb.connect()
    cols = ", ".join(
        f'"{r["name"]}" '
        + (
            STAGED_TYPES[r["dtype"]]
            if r["type"] == "VARCHAR" and r["dtype"] in STAGED_TYPES
            else r["type"]
        )
        for r in read_schema().iter_rows(named=True)
    )
    con.execute(f"CREATE TABLE {STAGE_TABLE} ({cols})")
    yield con
    con.close()
