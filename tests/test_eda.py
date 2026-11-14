from datetime import date

import pytest

from mf_scorecard import eda
from mf_scorecard.data.loans import build_loans
from mf_scorecard.data.stage import STAGE_TABLE


def add_loan(con, loan, acquired, ever_60, state, dscr, periods):
    for period in periods:
        values = {
            "loan_number": loan,
            "reporting_period_date": period,
            "acquisition_date": acquired,
            "loan_ever_60_plus_days_delinquent": ever_60,
            "property_state": state,
            "underwritten_dscr": dscr,
            "loan_acquisition_ltv": 70.0,
            "original_upb": 1e9,
        }
        names = ", ".join(f'"{k}"' for k in values)
        marks = ", ".join("?" for _ in values)
        con.execute(
            f"INSERT INTO {STAGE_TABLE} ({names}) VALUES ({marks})",
            list(values.values()),
        )


@pytest.fixture
def con(stage_con):
    # Data runs through 2024, so vintages up to 2021 are seasoned.
    add_loan(stage_con, "A", date(2020, 3, 31), True, "CA", 1.2, [date(2024, 1, 1)])
    add_loan(stage_con, "B", date(2020, 6, 30), False, "CA", 1.5, [date(2024, 1, 1)])
    add_loan(stage_con, "C", date(2023, 6, 30), False, "TX", None, [date(2024, 6, 1)])
    build_loans(stage_con)
    return stage_con


def test_overview(con):
    o = eda.overview(con)
    assert (o["n_loans"], o["n_ever_60"], o["original_upb_bn"]) == (3, 1, 3.0)


def test_vintages(con):
    v = eda.vintages(con)
    assert v["acquisition_year"].to_list() == [2020, 2023]
    assert v["n_loans"].to_list() == [2, 1]
    assert v["ever_60_pct"].to_list() == [50.0, 0.0]
    assert v["seasoned"].to_list() == [True, False]


def test_by_category(con):
    c = eda.by_category(con, "property_state")
    assert c.select("value", "n_loans", "pct_loans").rows() == [
        ("CA", 2, 66.7),
        ("TX", 1, 33.3),
    ]
    seasoned = eda.by_category(con, "property_state", seasoned_only=True)
    assert seasoned["value"].to_list() == ["CA"]


def test_dscr_definitions(stage_con):
    for loan, year, kind, dscr in [
        ("A", 2010, "Lender UW DSCR", 1.3),
        ("B", 2011, "Lender UW DSCR", 1.4),
        ("C", 2019, "UW DSCR NCF", 1.5),
    ]:
        stage_con.execute(
            f"INSERT INTO {STAGE_TABLE} (loan_number, reporting_period_date, "
            "acquisition_date, underwritten_dscr_type, underwritten_dscr) "
            "VALUES (?, ?, ?, ?, ?)",
            [loan, date(2024, 1, 1), date(year, 6, 30), kind, dscr],
        )
    build_loans(stage_con)
    d = eda.dscr_definitions(stage_con)
    assert d.select("dscr_type", "first_vintage", "last_vintage", "n_loans").rows() == [
        ("Lender UW DSCR", 2010, 2011, 2),
        ("UW DSCR NCF", 2019, 2019, 1),
    ]
    assert d["median_dscr"].to_list() == pytest.approx([1.35, 1.5])


def test_values_and_range_counts(con):
    assert sorted(eda.values(con, "underwritten_dscr").to_list()) == [1.2, 1.5]
    assert eda.range_counts(con, "underwritten_dscr", 1.3, 2) == {
        "below": 1,
        "inside": 1,
        "above": 0,
        "null": 1,
    }
