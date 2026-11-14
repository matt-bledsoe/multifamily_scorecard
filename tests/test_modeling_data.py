from datetime import date

import pytest

from mf_scorecard.data.defaults import DEFAULTS_TABLE, build_defaults
from mf_scorecard.data.loans import build_loans
from mf_scorecard.data.snapshots import (
    EXCLUDED,
    PERIOD_FEATURES,
    SNAPSHOTS_TABLE,
    STATIC_FEATURES,
    build_snapshots,
    default_rates,
    waterfall,
)
from mf_scorecard.data.stage import STAGE_TABLE

COVID = (date(2020, 4, 1), date(2020, 12, 1))
CFG = {
    "snapshot_month": 12,
    "horizon_months": 12,
    "oot_snapshot_years": [2009],
    "test_share_pct": 0,  # everything not OOT is train
}


def months(start: date, n: int) -> list[date]:
    out, y, m = [], start.year, start.month
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def add_history(con, loan, start, n, status=None, upb=1000.0, **loan_fields):
    """Monthly rows; ``status`` maps a month to a payment status."""
    status = status or {}
    for period in months(start, n):
        values = {
            "loan_number": loan,
            "reporting_period_date": period,
            "loan_payment_status": status.get(period, "Current"),
            "upb_current": upb,
            "original_upb": 1000.0,
            "note_date": start,
            "acquisition_date": start,
            "maturity_date_current": date(2030, 1, 1),
            **loan_fields,
        }
        names = ", ".join(f'"{k}"' for k in values)
        marks = ", ".join("?" for _ in values)
        con.execute(
            f"INSERT INTO {STAGE_TABLE} ({names}) VALUES ({marks})",
            list(values.values()),
        )


def build(con):
    build_loans(con)
    build_defaults(con, *COVID)
    build_snapshots(con, CFG)


def defaults(con):
    return {
        r[0]: r[1:]
        for r in con.execute(
            f"SELECT loan_number, default_month, default_trigger, covid_forbearance "
            f"FROM {DEFAULTS_TABLE}"
        ).fetchall()
    }


def snapshots(con, loan):
    return con.execute(
        f"SELECT snapshot_year, exclusion_reason, default_12m, sample "
        f"FROM {SNAPSHOTS_TABLE} WHERE loan_number = ? ORDER BY snapshot_year",
        [loan],
    ).fetchall()


@pytest.fixture
def con(stage_con):
    return stage_con


def test_default_is_earliest_event(con):
    # 90+ in Mar 2011, but the credit event is dated earlier, in Feb 2011.
    add_history(
        con,
        "A",
        date(2010, 1, 1),
        20,
        status={date(2011, 3, 1): "90+ Days Delinquent"},
        credit_event_date=date(2011, 2, 20),
    )
    # 60-89 only: not a default under the 90+ definition.
    add_history(
        con,
        "B",
        date(2010, 1, 1),
        20,
        status={date(2011, 3, 1): "60-89 Days Delinquent"},
    )
    build(con)
    d = defaults(con)
    assert d["A"] == (date(2011, 2, 1), "Credit event", False)
    assert d["B"] == (None, None, False)


def test_covid_flag(con):
    may = date(2020, 5, 1)
    add_history(con, "C", date(2019, 1, 1), 30, status={may: "90+ Days Delinquent"})
    # Same delinquency, but the loan later had a credit event: not flagged.
    add_history(
        con,
        "D",
        date(2019, 1, 1),
        30,
        status={may: "90+ Days Delinquent"},
        credit_event_date=date(2021, 3, 1),
    )
    build(con)
    d = defaults(con)
    assert d["C"] == (may, "90+ days delinquent", True)
    assert d["D"] == (may, "90+ days delinquent", False)


def test_distressed_exit_counts_but_prepayment_does_not(con):
    add_history(
        con,
        "E",
        date(2010, 1, 1),
        18,
        liquidation_prepayment_code="Third Party Sale",
        liquidation_prepayment_date=date(2011, 6, 15),
    )
    add_history(
        con,
        "F",
        date(2010, 1, 1),
        18,
        liquidation_prepayment_code="Fully Paid, Prepaid",
        liquidation_prepayment_date=date(2011, 6, 15),
    )
    build(con)
    d = defaults(con)
    assert d["E"][:2] == (date(2011, 6, 1), "Distressed exit")
    assert d["F"][0] is None


def test_snapshot_target_and_exclusions(con):
    # Data runs Jan 2008 - Jan 2012, so the Dec 2011 horizon is unobserved.
    add_history(
        con,
        "G",
        date(2008, 1, 1),
        49,
        status={date(2010, 6, 1): "90+ Days Delinquent"},
    )
    build(con)
    assert snapshots(con, "G") == [
        (2008, None, False, "train"),  # default Jun 2010 is > 12m after Dec 2008
        (2009, None, True, "oot"),  # Jun 2010 is within Dec 2009 + 12m
        (2010, "Defaulted before snapshot", False, "train"),
        (2011, "Defaulted before snapshot", False, "train"),
    ]


def test_horizon_not_observed_and_exits(con):
    # Pays off in Jun 2011; data for another loan runs to Jun 2012.
    add_history(
        con,
        "H",
        date(2010, 1, 1),
        18,
        liquidation_prepayment_code="Fully Paid, Prepaid",
        liquidation_prepayment_date=date(2011, 6, 10),
    )
    add_history(con, "I", date(2010, 1, 1), 30)
    build(con)
    [(exited,)] = con.execute(
        f"SELECT exited_in_horizon FROM {SNAPSHOTS_TABLE} "
        "WHERE loan_number = 'H' AND snapshot_year = 2010"
    ).fetchall()
    assert exited is True
    # Dec 2011 + 12 months = Dec 2012 is after the Jun 2012 data end.
    assert snapshots(con, "I")[-1][:2] == (2011, "Horizon not observed")

    w = waterfall(con)
    assert w.filter(snapshot_year=2011)["Horizon not observed"].item() == 1
    rates = default_rates(con)
    assert rates["snapshot_year"].to_list() == [2010]


def test_months_delinquent_last_12(con):
    status = {
        date(2010, 3, 1): "30-59 Days Delinquent",
        date(2010, 11, 1): "30-59 Days Delinquent",
    }
    add_history(con, "J", date(2010, 1, 1), 30, status=status)
    build(con)
    rows = con.execute(
        f"SELECT snapshot_year, months_delinquent_last_12, months_on_book "
        f"FROM {SNAPSHOTS_TABLE} WHERE loan_number = 'J' ORDER BY 1"
    ).fetchall()
    assert rows == [(2010, 2, 11), (2011, 0, 23)]


def test_no_leaking_columns_are_features():
    assert not set(EXCLUDED) & set(STATIC_FEATURES + PERIOD_FEATURES)
