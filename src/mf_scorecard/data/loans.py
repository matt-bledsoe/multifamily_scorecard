"""Split the staged loan x month panel into a loan table and a history table.

``loans`` has one row per loan:

- every schema column at level ``loan`` (acquisition attributes, plus a few
  loan-level outcomes Fannie Mae repeats on every row);
- every column at level ``event`` (payoff, foreclosure, credit event, loss
  amounts, defeasance), taking the single non-blank value, or blank if the
  event never happened;
- ``first_reporting_period``, ``last_reporting_period`` and
  ``n_reporting_periods`` summarising the loan's history.

``loan_performance`` has one row per loan and reporting period, with the
columns at level ``period`` (balance, payment status, note rate, ...).
Exact duplicate rows in the source are dropped, and the step fails if any
loan/period still has more than one row.

Using these tables:

- The event columns record *outcomes*. When building model features as of a
  snapshot date, only use an event column if its date is on or before the
  snapshot; otherwise the feature leaks the future.
- ``loan_age`` is not the loan's age in each period. It is the loan's age
  when it terminated (months from note date to last report) and is filled in
  almost only for paid-off or liquidated loans. Compute age from
  ``note_date`` instead.

Run after the quality checks: ``uv run python -m mf_scorecard.data.loans``
"""

import duckdb

from mf_scorecard.config import load_config, repo_path
from mf_scorecard.data.load import columns_at_level
from mf_scorecard.data.stage import STAGE_TABLE

LOANS_TABLE = "loans"
PERFORMANCE_TABLE = "loan_performance"


def _cols(names: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in names)


def loans_sql() -> str:
    loan_cols = columns_at_level("loan")
    event_cols = columns_at_level("event")
    # The quality checks guarantee one value per loan for these columns, so
    # any_value (which skips blanks) is exact rather than an arbitrary pick.
    picks = [f'any_value("{c}") AS "{c}"' for c in loan_cols if c != "loan_number"]
    picks += [f'any_value("{c}") AS "{c}"' for c in event_cols]
    return (
        f"SELECT loan_number, {', '.join(picks)}, "
        "min(reporting_period_date) AS first_reporting_period, "
        "max(reporting_period_date) AS last_reporting_period, "
        "count(DISTINCT reporting_period_date) AS n_reporting_periods "
        f"FROM {STAGE_TABLE} GROUP BY loan_number ORDER BY loan_number"
    )


def performance_sql() -> str:
    period_cols = columns_at_level("period")
    return (
        f"SELECT DISTINCT loan_number, {_cols(period_cols)} FROM {STAGE_TABLE} "
        "ORDER BY loan_number, reporting_period_date"
    )


def build_loans(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE OR REPLACE TABLE {LOANS_TABLE} AS {loans_sql()}")
    con.execute(f"CREATE OR REPLACE TABLE {PERFORMANCE_TABLE} AS {performance_sql()}")

    [(dupes,)] = con.execute(
        f"SELECT count(*) FROM (SELECT 1 FROM {PERFORMANCE_TABLE} "
        "GROUP BY loan_number, reporting_period_date HAVING count(*) > 1)"
    ).fetchall()
    if dupes:
        raise ValueError(
            f"{dupes} loan/period keys in {PERFORMANCE_TABLE} still have "
            "differing rows after dropping exact duplicates."
        )
    [(n_stage_loans, n_loans, n_perf_loans)] = con.execute(
        f"SELECT (SELECT count(DISTINCT loan_number) FROM {STAGE_TABLE}), "
        f"(SELECT count(*) FROM {LOANS_TABLE}), "
        f"(SELECT count(DISTINCT loan_number) FROM {PERFORMANCE_TABLE})"
    ).fetchall()
    if not n_stage_loans == n_loans == n_perf_loans:
        raise ValueError(
            f"Loan counts differ: stage {n_stage_loans}, {LOANS_TABLE} "
            f"{n_loans}, {PERFORMANCE_TABLE} {n_perf_loans}"
        )


def main() -> None:
    database = repo_path(load_config()["data"]["database"])
    with duckdb.connect(str(database)) as con:
        build_loans(con)
        for table in (LOANS_TABLE, PERFORMANCE_TABLE):
            [(n_rows, n_cols)] = con.execute(
                f"SELECT (SELECT count(*) FROM {table}), "
                f"(SELECT count(*) FROM (DESCRIBE {table}))"
            ).fetchall()
            print(f"{table}: {n_rows:,} rows, {n_cols} columns")


if __name__ == "__main__":
    main()
