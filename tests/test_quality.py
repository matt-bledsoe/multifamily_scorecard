from datetime import date

import duckdb
import pytest

from mf_scorecard.data.load import read_schema
from mf_scorecard.data.quality import (
    CHECKS,
    STATIC_COLUMNS,
    Check,
    missingness,
    run_check,
    run_checks,
)
from mf_scorecard.data.stage import STAGE_TABLE

DUCKDB_TYPES = {"Float64": "DOUBLE", "Int64": "INTEGER", "Boolean": "BOOLEAN"}

GOOD_ROW = {
    "loan_number": "001",
    "reporting_period_date": date(2020, 2, 1),
    "acquisition_date": date(2020, 1, 31),
    "note_date": date(2020, 1, 15),
    "maturity_date_at_acquisition": date(2030, 2, 1),
    "original_upb": 1_000_000.0,
    "loan_acquisition_upb": 1_000_000.0,
    "upb_current": 990_000.0,
    "original_term": 120,
    "original_io_term": 0,
    "original_interest_rate": 5.0,
    "note_rate": 5.0,
    "loan_acquisition_ltv": 70.0,
    "underwritten_dscr": 1.4,
    "physical_occupancy_pct": 95.0,
    "loan_age": 1,
    "year_built": 1985,
    "loan_payment_status": "Current",
    "sdq_indicator": False,
}


@pytest.fixture
def con():
    """In-memory DB with an empty stage table typed like the real one."""
    con = duckdb.connect()
    cols = ", ".join(
        f'"{r["name"]}" '
        + (
            DUCKDB_TYPES[r["dtype"]]
            if r["type"] == "VARCHAR" and r["dtype"] in DUCKDB_TYPES
            else r["type"]
        )
        for r in read_schema().iter_rows(named=True)
    )
    con.execute(f"CREATE TABLE {STAGE_TABLE} ({cols})")
    yield con
    con.close()


def insert(con, **overrides):
    row = {**GOOD_ROW, **overrides}
    names = ", ".join(f'"{k}"' for k in row)
    marks = ", ".join("?" for _ in row)
    con.execute(
        f"INSERT INTO {STAGE_TABLE} ({names}) VALUES ({marks})", list(row.values())
    )


def check(name):
    return next(c for c in CHECKS if c.name == name)


def test_check_names_unique():
    names = [c.name for c in CHECKS]
    assert len(names) == len(set(names))


def test_static_columns_exist_in_schema():
    assert set(STATIC_COLUMNS) <= set(read_schema()["name"])


def test_bad_severity_rejected():
    with pytest.raises(ValueError, match="bad severity"):
        Check("x", "fatal", "", "SELECT 1")


def test_clean_data_passes_all_checks(con):
    insert(con)
    insert(con, reporting_period_date=date(2020, 3, 1))
    results = run_checks(con)
    assert results["passed"].all(), results.filter(~results["passed"])


def test_month_level_date_comparison(con):
    # Acquired 31 Jan, first reported 1 Jan: same month, so not a violation.
    insert(con, reporting_period_date=date(2020, 1, 1))
    assert run_check(con, check("acquisition_month_not_after_reporting"))["passed"]
    insert(con, loan_number="002", reporting_period_date=date(2019, 12, 1))
    result = run_check(con, check("acquisition_month_not_after_reporting"))
    assert (result["n_loans"], result["example_loans"]) == (1, "002")


def test_static_attribute_varying(con):
    insert(con)
    insert(con, reporting_period_date=date(2020, 3, 1), original_upb=2_000_000.0)
    result = run_check(con, check("static_original_upb"))
    assert (result["passed"], result["n_loans"]) == (False, 1)


def test_sdq_mismatch(con):
    insert(con, loan_payment_status="90+ Days Delinquent", sdq_indicator=False)
    assert not run_check(con, check("sdq_matches_payment_status"))["passed"]


def test_duplicates_and_gaps(con):
    insert(con)
    insert(con)
    insert(con, reporting_period_date=date(2020, 5, 1))
    assert run_check(con, check("duplicate_loan_period"))["n_rows"] == 1
    assert run_check(con, check("history_gaps"))["n_loans"] == 1


def test_missingness(con):
    insert(con)
    insert(con, note_rate=None)
    insert(con, acquisition_date=date(2021, 1, 31), note_rate=None)
    m = missingness(con).filter(column="note_rate")
    assert m.select("acquisition_year", "n_null", "pct_null").rows() == [
        (2020, 1, 50.0),
        (2021, 1, 100.0),
    ]
