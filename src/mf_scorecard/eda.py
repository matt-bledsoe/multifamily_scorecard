"""Queries behind the exploratory data analysis report (docs/).

All functions read the ``loans`` table built by ``mf_scorecard.data.loans``
and return polars DataFrames, so the report only formats and plots.
"""

import duckdb
import polars as pl

from mf_scorecard.data.loans import LOANS_TABLE

# A vintage needs this many years of history before its ever-60+ rate means
# much; younger vintages are shown but marked as not yet seasoned.
SEASONING_YEARS = 3

EVER_60 = "loan_ever_60_plus_days_delinquent"


def data_through(con: duckdb.DuckDBPyConnection) -> int:
    """Calendar year of the latest reporting period in the data."""
    [(year,)] = con.execute(
        f"SELECT year(max(last_reporting_period)) FROM {LOANS_TABLE}"
    ).fetchall()
    return year


def overview(con: duckdb.DuckDBPyConnection) -> dict:
    [row] = con.execute(
        f"""SELECT count(*), sum(original_upb) / 1e9,
            min(acquisition_date), max(acquisition_date),
            min(first_reporting_period), max(last_reporting_period),
            count(*) FILTER ({EVER_60}),
            count(*) FILTER (credit_event_type IS NOT NULL),
            count(*) FILTER (liquidation_prepayment_code IS NOT NULL)
        FROM {LOANS_TABLE}"""
    ).fetchall()
    keys = [
        "n_loans",
        "original_upb_bn",
        "first_acquisition",
        "last_acquisition",
        "first_period",
        "last_period",
        "n_ever_60",
        "n_credit_events",
        "n_terminated",
    ]
    return dict(zip(keys, row))


def vintages(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """One row per acquisition year."""
    cutoff = data_through(con) - SEASONING_YEARS
    return con.sql(
        f"""SELECT year(acquisition_date) AS acquisition_year,
            count(*) AS n_loans,
            round(sum(original_upb) / 1e9, 1) AS original_upb_bn,
            round(100 * avg({EVER_60}::INT), 2) AS ever_60_pct,
            median(underwritten_dscr) AS median_dscr,
            median(loan_acquisition_ltv) AS median_ltv,
            round(100 * avg((liquidation_prepayment_code IS NOT NULL)::INT), 1)
                AS terminated_pct,
            year(acquisition_date) <= {cutoff} AS seasoned
        FROM {LOANS_TABLE} GROUP BY ALL ORDER BY acquisition_year"""
    ).pl()


def by_category(
    con: duckdb.DuckDBPyConnection, column: str, seasoned_only: bool = False
) -> pl.DataFrame:
    """Loan count, share and ever-60+ rate for each value of ``column``.

    With ``seasoned_only``, restrict to vintages with at least
    ``SEASONING_YEARS`` of history so young loans don't dilute the rate.
    """
    where = ""
    if seasoned_only:
        cutoff = data_through(con) - SEASONING_YEARS
        where = f"WHERE year(acquisition_date) <= {cutoff}"
    return con.sql(
        f"""SELECT "{column}" AS value,
            count(*) AS n_loans,
            round(100 * count(*) / sum(count(*)) OVER (), 1) AS pct_loans,
            round(100 * avg({EVER_60}::INT), 2) AS ever_60_pct
        FROM {LOANS_TABLE} {where}
        GROUP BY ALL ORDER BY n_loans DESC, value"""
    ).pl()


def dscr_definitions(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Which DSCR definition each vintage uses, and how they differ."""
    return con.sql(
        f"""SELECT underwritten_dscr_type AS dscr_type,
            min(year(acquisition_date)) AS first_vintage,
            max(year(acquisition_date)) AS last_vintage,
            mode(year(acquisition_date)) AS main_vintage,
            count(*) AS n_loans,
            median(underwritten_dscr) AS median_dscr
        FROM {LOANS_TABLE} WHERE underwritten_dscr_type IS NOT NULL
        GROUP BY ALL ORDER BY min(acquisition_date)"""
    ).pl()


def values(con: duckdb.DuckDBPyConnection, column: str) -> pl.Series:
    """All non-null values of a loan-level column."""
    return con.sql(
        f'SELECT "{column}" FROM {LOANS_TABLE} WHERE "{column}" IS NOT NULL'
    ).pl()[column]


def range_counts(
    con: duckdb.DuckDBPyConnection, column: str, low: float, high: float
) -> dict:
    """How many loans fall below, inside and above [low, high], or are null."""
    [row] = con.execute(
        f"""SELECT count(*) FILTER ("{column}" < {low}),
            count(*) FILTER ("{column}" BETWEEN {low} AND {high}),
            count(*) FILTER ("{column}" > {high}),
            count(*) FILTER ("{column}" IS NULL)
        FROM {LOANS_TABLE}"""
    ).fetchall()
    return dict(zip(["below", "inside", "above", "null"], row))
