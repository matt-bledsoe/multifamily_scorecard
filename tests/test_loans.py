from datetime import date

import pytest

from mf_scorecard.data.load import columns_at_level, read_schema
from mf_scorecard.data.loans import LOANS_TABLE, PERFORMANCE_TABLE, build_loans
from mf_scorecard.data.stage import STAGE_TABLE


@pytest.fixture
def con(stage_con):
    return stage_con


def insert(con, **values):
    names = ", ".join(f'"{k}"' for k in values)
    marks = ", ".join("?" for _ in values)
    con.execute(
        f"INSERT INTO {STAGE_TABLE} ({names}) VALUES ({marks})", list(values.values())
    )


def history(con, loan, periods, **static):
    """One row per period; ``static`` values repeat on every row."""
    for i, (period, extra) in enumerate(periods):
        insert(
            con,
            loan_number=loan,
            reporting_period_date=period,
            upb_current=1000.0 - i,
            **static,
            **extra,
        )


def test_levels_cover_schema_once():
    names = read_schema()["name"].to_list()
    by_level = [c for lvl in ("loan", "event", "period") for c in columns_at_level(lvl)]
    assert sorted(by_level) == sorted(names)


def test_bad_level_rejected():
    with pytest.raises(ValueError, match="level must be"):
        columns_at_level("monthly")


def test_build_loans(con):
    history(
        con,
        "001",
        [
            (date(2020, 1, 1), {}),
            (date(2020, 2, 1), {}),
            (
                date(2020, 3, 1),
                {
                    "liquidation_prepayment_code": "Fully Paid, Prepaid",
                    "liquidation_prepayment_date": date(2020, 3, 15),
                },
            ),
        ],
        original_upb=1000.0,
        property_state="CA",
    )
    history(con, "002", [(date(2020, 2, 1), {})], original_upb=500.0)
    # Exact duplicate of loan 002's only row: dropped.
    insert(
        con,
        loan_number="002",
        reporting_period_date=date(2020, 2, 1),
        upb_current=1000.0,
        original_upb=500.0,
    )
    build_loans(con)

    loans = con.sql(f"SELECT * FROM {LOANS_TABLE} ORDER BY loan_number").pl()
    assert loans["loan_number"].to_list() == ["001", "002"]
    first = loans.row(0, named=True)
    assert first["original_upb"] == 1000.0
    assert first["property_state"] == "CA"
    assert first["liquidation_prepayment_code"] == "Fully Paid, Prepaid"
    assert first["liquidation_prepayment_date"] == date(2020, 3, 15)
    assert (first["first_reporting_period"], first["last_reporting_period"]) == (
        date(2020, 1, 1),
        date(2020, 3, 1),
    )
    assert first["n_reporting_periods"] == 3
    assert loans.row(1, named=True)["liquidation_prepayment_code"] is None

    perf = con.sql(f"SELECT * FROM {PERFORMANCE_TABLE}").pl()
    assert perf.height == 4
    assert set(perf.columns) == {"loan_number", *columns_at_level("period")}


def test_conflicting_duplicates_raise(con):
    insert(
        con, loan_number="001", reporting_period_date=date(2020, 1, 1), upb_current=1.0
    )
    insert(
        con, loan_number="001", reporting_period_date=date(2020, 1, 1), upb_current=2.0
    )
    with pytest.raises(ValueError, match="still have differing rows"):
        build_loans(con)
