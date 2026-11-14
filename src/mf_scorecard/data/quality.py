"""Completeness and accuracy checks on the staged MFLPD table.

Each check is a SQL query that returns the rows breaking a rule. Checks have
a severity:

- ``error``: an invariant the data must satisfy. Any violation stops the
  pipeline, so a format or meaning change in a new release is caught here.
- ``warning``: a known data issue. Violations are counted and reported, and
  are handled downstream (e.g. duplicates are removed when the loan-level
  table is built). A large change in a warning's count between releases is
  worth investigating even though it doesn't stop the pipeline.

Dates are compared at month level: MFLPD reporting periods are the first of
the month while acquisition and event dates fall anywhere in the month.

Results go to ``reports/data_quality/<raw file stem>/`` (committed) and to
the ``dq_checks`` and ``dq_missingness`` tables in the database.

Run after staging: ``uv run python -m mf_scorecard.data.quality``
"""

import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import polars as pl

from mf_scorecard.config import REPO_ROOT, load_config, repo_path
from mf_scorecard.data.load import read_schema
from mf_scorecard.data.stage import STAGE_TABLE

CHECKS_TABLE = "dq_checks"
MISSINGNESS_TABLE = "dq_missingness"
N_EXAMPLES = 5

# Attributes fixed at acquisition: must not vary across a loan's history.
STATIC_COLUMNS = [
    "acquisition_date",
    "note_date",
    "maturity_date_at_acquisition",
    "loan_acquisition_upb",
    "original_upb",
    "original_interest_rate",
    "original_term",
    "amortization_type",
    "interest_type",
    "loan_product_type",
    "loan_acquisition_ltv",
    "underwritten_dscr",
    "specific_property_type",
    "property_state",
    "year_built",
    "loan_ever_60_plus_days_delinquent",
    "liquidation_prepayment_code",
    "liquidation_prepayment_date",
    "credit_event_type",
    # Despite its name, loan_age is the loan's age when it terminated (months
    # from note date to last report), not its age in each reporting period.
    # It is filled in almost only for paid-off/liquidated loans.
    "loan_age",
]

REQUIRED_COLUMNS = [
    "loan_number",
    "reporting_period_date",
    "acquisition_date",
    "note_date",
    "original_upb",
    "upb_current",
    "original_term",
    "loan_payment_status",
    "sdq_indicator",
]

NON_NEGATIVE_COLUMNS = [
    "loan_acquisition_upb",
    "original_upb",
    "upb_current",
    "delinquency_upb",
    "foreclosure_value",
    "sale_price",
    "default_amount",
]


def month(col: str) -> str:
    return f"date_trunc('month', {col})"


@dataclass(frozen=True)
class Check:
    name: str
    severity: str  # "error" or "warning"
    description: str
    sql: str  # returns violating rows; must include loan_number

    def __post_init__(self):
        if self.severity not in ("error", "warning"):
            raise ValueError(f"{self.name}: bad severity {self.severity!r}")


def rows_where(condition: str) -> str:
    return f"SELECT loan_number FROM {STAGE_TABLE} WHERE {condition}"


def static_check(col: str) -> Check:
    return Check(
        f"static_{col}",
        "error",
        f"{col} is constant within each loan",
        f"SELECT loan_number FROM {STAGE_TABLE} GROUP BY loan_number "
        f"HAVING count(DISTINCT {col}) > 1",
    )


CHECKS: list[Check] = [
    # --- Structure -----------------------------------------------------------
    *(
        Check(
            f"required_{c}",
            "error",
            f"{c} is never null",
            rows_where(f"{c} IS NULL"),
        )
        for c in REQUIRED_COLUMNS
    ),
    Check(
        "reporting_period_first_of_month",
        "error",
        "Reporting periods fall on the first of the month",
        rows_where("day(reporting_period_date) <> 1"),
    ),
    *(static_check(c) for c in STATIC_COLUMNS),
    Check(
        "duplicate_loan_period",
        "warning",
        "At most one row per loan and reporting period",
        f"SELECT loan_number FROM {STAGE_TABLE} "
        "GROUP BY loan_number, reporting_period_date HAVING count(*) > 1",
    ),
    Check(
        "history_gaps",
        "warning",
        "Each loan has a row for every month between its first and last",
        f"SELECT loan_number FROM {STAGE_TABLE} GROUP BY loan_number "
        "HAVING count(DISTINCT reporting_period_date) <> "
        "date_diff('month', min(reporting_period_date), "
        "max(reporting_period_date)) + 1",
    ),
    Check(
        "rows_after_liquidation",
        "warning",
        "No reporting periods after the liquidation/prepayment month",
        rows_where(f"reporting_period_date > {month('liquidation_prepayment_date')}"),
    ),
    # --- Consistency between fields -----------------------------------------
    Check(
        "sdq_matches_payment_status",
        "error",
        "SDQ indicator is true exactly when the loan is 60+ days delinquent",
        rows_where(
            "sdq_indicator <> (loan_payment_status IN "
            "('60-89 Days Delinquent', '90+ Days Delinquent'))"
        ),
    ),
    Check(
        "maturity_after_note",
        "error",
        "Maturity at acquisition is after the note date",
        rows_where("maturity_date_at_acquisition <= note_date"),
    ),
    Check(
        "maturity_after_acquisition",
        "error",
        "Maturity at acquisition is after the acquisition date",
        rows_where("maturity_date_at_acquisition <= acquisition_date"),
    ),
    Check(
        "note_month_not_after_acquisition",
        "warning",
        "Note month is not after the acquisition month",
        rows_where(f"{month('note_date')} > {month('acquisition_date')}"),
    ),
    Check(
        "acquisition_month_not_after_reporting",
        "warning",
        "No reporting periods before the acquisition month",
        rows_where(f"{month('acquisition_date')} > reporting_period_date"),
    ),
    Check(
        "liquidation_not_before_acquisition",
        "warning",
        "Liquidation/prepayment month is not before the acquisition month",
        rows_where(
            f"{month('liquidation_prepayment_date')} < {month('acquisition_date')}"
        ),
    ),
    Check(
        "io_term_within_term",
        "warning",
        "Interest-only term does not exceed the original term",
        rows_where("original_io_term > original_term"),
    ),
    Check(
        "upb_not_above_original",
        "warning",
        "Current UPB is at most 1% above original UPB",
        rows_where("upb_current > original_upb * 1.01"),
    ),
    # --- Ranges --------------------------------------------------------------
    *(
        Check(
            f"non_negative_{c}",
            "error",
            f"{c} is not negative",
            rows_where(f"{c} < 0"),
        )
        for c in NON_NEGATIVE_COLUMNS
    ),
    Check(
        "interest_rate_range",
        "error",
        "Original interest rate and note rate are in (0%, 15%]",
        rows_where(
            "NOT (original_interest_rate > 0 AND original_interest_rate <= 15) "
            "OR NOT (note_rate > 0 AND note_rate <= 15)"
        ),
    ),
    Check(
        "original_term_positive",
        "error",
        "Original term is positive",
        rows_where("original_term <= 0"),
    ),
    Check(
        "ltv_range",
        "warning",
        "Acquisition LTV is in (0%, 100%]",
        rows_where("NOT (loan_acquisition_ltv > 0 AND loan_acquisition_ltv <= 100)"),
    ),
    Check(
        "dscr_range",
        "warning",
        "Underwritten DSCR is in [0.75, 10]",
        rows_where("NOT (underwritten_dscr BETWEEN 0.75 AND 10)"),
    ),
    Check(
        "occupancy_range",
        "warning",
        "Physical occupancy is in (0%, 100%]; 0 likely means not reported",
        rows_where(
            "NOT (physical_occupancy_pct > 0 AND physical_occupancy_pct <= 100)"
        ),
    ),
    Check(
        "loan_age_non_negative",
        "warning",
        "Loan age is not negative",
        rows_where("loan_age < 0"),
    ),
    Check(
        "year_built_plausible",
        "warning",
        "Year built is between 1800 and two years after acquisition",
        rows_where("year_built < 1800 OR year_built > year(acquisition_date) + 2"),
    ),
]


def run_check(con: duckdb.DuckDBPyConnection, check: Check) -> dict:
    # fetchall() rather than fetchone(): DuckDB 2.x blocks further con.sql()
    # work while an execute() result is only partly read.
    [(n_rows, n_loans, examples)] = con.execute(
        f"SELECT count(*), count(DISTINCT loan_number), "
        f"list(DISTINCT loan_number ORDER BY loan_number)[1:{N_EXAMPLES}] "
        f"FROM ({check.sql})"
    ).fetchall()
    return {
        "check": check.name,
        "severity": check.severity,
        "description": check.description,
        "n_rows": n_rows,
        "n_loans": n_loans,
        "passed": n_rows == 0,
        "example_loans": ", ".join(examples or []),
    }


def run_checks(
    con: duckdb.DuckDBPyConnection, checks: list[Check] = CHECKS
) -> pl.DataFrame:
    names = [c.name for c in checks]
    if len(names) != len(set(names)):
        raise ValueError("Check names must be unique")
    return pl.DataFrame([run_check(con, c) for c in checks])


def missingness(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Share of null values per column, by acquisition year (row level)."""
    cols = read_schema()["name"].to_list()
    nulls = ", ".join(f'count(*) FILTER ("{c}" IS NULL) AS "{c}"' for c in cols)
    wide = con.sql(
        f"SELECT year(acquisition_date) AS acquisition_year, count(*) AS n_rows, "
        f"{nulls} FROM {STAGE_TABLE} GROUP BY ALL ORDER BY ALL"
    ).pl()
    return (
        wide.unpivot(
            index=["acquisition_year", "n_rows"],
            variable_name="column",
            value_name="n_null",
        )
        .with_columns(pct_null=(100 * pl.col("n_null") / pl.col("n_rows")).round(2))
        .select("column", "acquisition_year", "n_rows", "n_null", "pct_null")
        .sort("column", "acquisition_year")
    )


def save(
    con: duckdb.DuckDBPyConnection,
    checks: pl.DataFrame,
    missing: pl.DataFrame,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    checks.write_csv(out_dir / "checks.csv")
    missing.write_csv(out_dir / "missingness.csv")
    con.register("_checks", checks)
    con.register("_missing", missing)
    con.execute(f"CREATE OR REPLACE TABLE {CHECKS_TABLE} AS SELECT * FROM _checks")
    con.execute(
        f"CREATE OR REPLACE TABLE {MISSINGNESS_TABLE} AS SELECT * FROM _missing"
    )


def main() -> int:
    cfg = load_config()["data"]
    out_dir = repo_path(cfg["report_dir"]) / Path(cfg["raw_file"]).stem
    with duckdb.connect(str(repo_path(cfg["database"]))) as con:
        checks = run_checks(con)
        save(con, checks, missingness(con), out_dir)

    with pl.Config(tbl_rows=-1, tbl_width_chars=120, fmt_str_lengths=40):
        print(checks.select("check", "severity", "n_rows", "n_loans", "passed"))
    print(f"Wrote {out_dir.relative_to(REPO_ROOT)}/")

    failed = checks.filter((pl.col("severity") == "error") & ~pl.col("passed"))
    if failed.height:
        print(f"{failed.height} error check(s) failed: {failed['check'].to_list()}")
        return 1
    n_warn = checks.filter(~pl.col("passed")).height
    print(f"All error checks passed; {n_warn} warning check(s) have violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
