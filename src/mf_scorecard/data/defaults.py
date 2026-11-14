"""Default definition: the first month each loan defaults.

A loan defaults in the earliest month in which any of these happens:

- it is reported 90+ days delinquent;
- it has a credit event (REO or non-REO loss), dated by ``credit_event_date``;
- foreclosure starts (``foreclosure_date``);
- it leaves the data through a distressed exit: foreclosure, deed-in-lieu,
  third-party sale or discounted payoff.

This follows the regulatory definition of default used for bank rating
systems: 90 days past due, or an event showing the borrower is unlikely to
pay. Only the first default counts; a loan leaves the modeling sample once
it has defaulted, even if it later cures.

``Other Liquidation`` exits are not counted on their own: the code does not
say whether the exit was distressed. Those that were are caught by a credit
event.

COVID forbearance: in 2020, many loans in forbearance were reported 90+
days delinquent while their payments were paused, then cured. Defaults
triggered by a 90+ delinquency inside the configured COVID window, on loans
that never had a credit event, foreclosure or distressed exit, are flagged
``covid_forbearance``. They remain defaults; the flag lets models be fit and
compared with and without them.

Run after ``mf_scorecard.data.loans``:
``uv run python -m mf_scorecard.data.defaults``
"""

from datetime import date

import duckdb

from mf_scorecard.config import load_config, repo_path
from mf_scorecard.data.loans import LOANS_TABLE, PERFORMANCE_TABLE

DEFAULTS_TABLE = "loan_defaults"

DISTRESSED_EXITS = (
    "Foreclosure",
    "Deed-in-Lieu",
    "Third Party Sale",
    "Discounted Payoff",
)

# Order used to name the trigger when several happen in the same month.
TRIGGERS = [
    ("first_90_month", "90+ days delinquent"),
    ("credit_event_month", "Credit event"),
    ("foreclosure_month", "Foreclosure"),
    ("distressed_exit_month", "Distressed exit"),
]


def defaults_sql(covid_start: date, covid_end: date) -> str:
    exits = ", ".join(f"'{e}'" for e in DISTRESSED_EXITS)
    months = ", ".join(col for col, _ in TRIGGERS)
    trigger = " ".join(
        f"WHEN default_month = {col} THEN '{name}'" for col, name in TRIGGERS
    )
    return f"""
    WITH events AS (
        SELECT
            l.loan_number,
            p.first_90_month,
            date_trunc('month', l.credit_event_date)::DATE AS credit_event_month,
            date_trunc('month', l.foreclosure_date)::DATE AS foreclosure_month,
            CASE WHEN l.liquidation_prepayment_code IN ({exits})
                THEN date_trunc('month', l.liquidation_prepayment_date)::DATE
            END AS distressed_exit_month
        FROM {LOANS_TABLE} l
        LEFT JOIN (
            SELECT loan_number,
                min(reporting_period_date)
                    FILTER (loan_payment_status = '90+ Days Delinquent')
                    AS first_90_month
            FROM {PERFORMANCE_TABLE} GROUP BY loan_number
        ) p USING (loan_number)
    ),
    dated AS (
        SELECT *, least({months}) AS default_month FROM events
    )
    SELECT
        loan_number,
        default_month,
        CASE {trigger} END AS default_trigger,
        {months},
        coalesce(
            default_month = first_90_month
            AND first_90_month BETWEEN DATE '{covid_start}' AND DATE '{covid_end}'
            AND credit_event_month IS NULL
            AND foreclosure_month IS NULL
            AND distressed_exit_month IS NULL,
            false
        ) AS covid_forbearance
    FROM dated
    ORDER BY loan_number
    """


def build_defaults(
    con: duckdb.DuckDBPyConnection, covid_start: date, covid_end: date
) -> None:
    con.execute(
        f"CREATE OR REPLACE TABLE {DEFAULTS_TABLE} AS "
        f"{defaults_sql(covid_start, covid_end)}"
    )


def main() -> None:
    cfg = load_config()
    m = cfg["modeling"]
    with duckdb.connect(str(repo_path(cfg["data"]["database"]))) as con:
        build_defaults(con, m["covid_window_start"], m["covid_window_end"])
        print(
            con.sql(
                f"SELECT default_trigger, count(*) AS loans, "
                f"count(*) FILTER (covid_forbearance) AS covid_forbearance "
                f"FROM {DEFAULTS_TABLE} GROUP BY ALL ORDER BY loans DESC"
            )
        )


if __name__ == "__main__":
    main()
