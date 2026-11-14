"""Build the one-year-horizon modeling dataset from annual snapshots.

Each December (``snapshot_month``) reporting period, every loan with a row
in ``loan_performance`` is a candidate observation. The target is whether
the loan defaults (``loan_defaults.default_month``) in the following
``horizon_months`` months.

Candidates are excluded, with the first matching reason recorded in
``exclusion_reason``, when:

1. the loan has already defaulted (only first defaults are modeled);
2. the loan paid off or was liquidated in or before the snapshot month;
3. the current balance is zero;
4. the data does not yet cover the full horizon after the snapshot.

Loans that pay off or leave the data during the horizon without defaulting
count as non-defaults, and are flagged ``exited_in_horizon``.

Features are limited to what was known at the snapshot date:
acquisition attributes from ``loans`` and the snapshot month's values from
``loan_performance``, plus a few derived from the loan's history up to the
snapshot. Outcome fields are deliberately left out (see ``EXCLUDED``).

Each eligible row is assigned a ``sample``: ``oot`` for the out-of-time
snapshot years, otherwise ``test`` or ``train`` by a hash of the loan number,
so all of a loan's snapshots fall on the same side.

Run after ``mf_scorecard.data.defaults``:
``uv run python -m mf_scorecard.data.snapshots``
"""

from pathlib import Path

import duckdb
import polars as pl

from mf_scorecard.config import REPO_ROOT, load_config, repo_path
from mf_scorecard.data.defaults import DEFAULTS_TABLE
from mf_scorecard.data.loans import LOANS_TABLE, PERFORMANCE_TABLE

SNAPSHOTS_TABLE = "snapshots"

# Acquisition attributes from the loans table used as features.
STATIC_FEATURES = [
    "acquisition_date",
    "note_date",
    "original_upb",
    "original_interest_rate",
    "original_term",
    "amortization_term",
    "original_io_term",
    "amortization_type",
    "interest_type",
    "loan_product_type",
    "lien_position",
    "loan_acquisition_ltv",
    "underwritten_dscr",
    "underwritten_dscr_type",
    "number_of_properties_at_acquisition",
    "property_acquisition_total_unit_count",
    "specific_property_type",
    "year_built",
    "property_state",
    "metropolitan_statistical_area",
    "physical_occupancy_pct",
    "loss_sharing_type",
    "affordable_housing_type",
]

# Snapshot-month values from loan_performance.
PERIOD_FEATURES = [
    "upb_current",
    "note_rate",
    "loan_payment_status",
    "loan_active_property_count",
    "modification_indicator",
    "maturity_date_current",
]

# Columns that must never be features: they record outcomes after the
# snapshot (or the loan's whole life), so using them would leak the target.
EXCLUDED = {
    "loan_ever_60_plus_days_delinquent": "flags delinquency at any time, "
    "including after the snapshot",
    "loan_age": "age at termination, known only once the loan ends",
    "credit_event_type": "outcome of a credit event",
    "dus_prepayment_outcomes": "how the loan eventually paid off",
    "liquidation_prepayment_code": "how the loan left the data",
    "mcirt_deal_id": "credit risk transfer deal, assigned after acquisition",
    "mcas_deal_id": "credit risk transfer deal, assigned after acquisition",
}


def snapshots_sql(cfg: dict, data_end: str) -> str:
    month = cfg["snapshot_month"]
    horizon = cfg["horizon_months"]
    oot = ", ".join(str(y) for y in cfg["oot_snapshot_years"]) or "NULL"
    test_pct = cfg["test_share_pct"]
    static = ", ".join(f'l."{c}"' for c in STATIC_FEATURES)
    period = ", ".join(f'h."{c}"' for c in PERIOD_FEATURES)
    return f"""
    WITH history AS (
        SELECT *,
            count(*) FILTER (loan_payment_status <> 'Current') OVER w
                AS months_delinquent_last_12,
            count(*) FILTER (modification_indicator) OVER w
                AS months_modified_last_12
        FROM {PERFORMANCE_TABLE}
        WINDOW w AS (
            PARTITION BY loan_number ORDER BY reporting_period_date
            RANGE BETWEEN INTERVAL 11 MONTH PRECEDING AND CURRENT ROW
        )
    ),
    candidates AS (
        SELECT
            h.loan_number,
            year(h.reporting_period_date) AS snapshot_year,
            h.reporting_period_date AS snapshot_date,
            (h.reporting_period_date + INTERVAL {horizon} MONTH)::DATE
                AS horizon_end,
            d.default_month,
            d.default_trigger,
            d.covid_forbearance,
            l.liquidation_prepayment_date,
            l.last_reporting_period,
            {static},
            {period},
            h.months_delinquent_last_12,
            h.months_modified_last_12
        FROM history h
        JOIN {LOANS_TABLE} l USING (loan_number)
        JOIN {DEFAULTS_TABLE} d USING (loan_number)
        WHERE month(h.reporting_period_date) = {month}
    )
    SELECT
        loan_number,
        snapshot_year,
        snapshot_date,
        CASE
            WHEN default_month <= snapshot_date
                THEN 'Defaulted before snapshot'
            WHEN date_trunc('month', liquidation_prepayment_date) <= snapshot_date
                THEN 'Paid off or liquidated'
            WHEN upb_current <= 0 THEN 'Zero balance'
            WHEN horizon_end > DATE '{data_end}' THEN 'Horizon not observed'
        END AS exclusion_reason,
        coalesce(default_month > snapshot_date AND default_month <= horizon_end,
                 false) AS default_12m,
        CASE WHEN default_month > snapshot_date AND default_month <= horizon_end
            THEN default_trigger END AS default_trigger,
        coalesce(default_month > snapshot_date AND default_month <= horizon_end
                 AND covid_forbearance, false) AS covid_forbearance,
        NOT coalesce(default_month <= horizon_end, false)
            AND last_reporting_period < horizon_end AS exited_in_horizon,
        CASE
            WHEN snapshot_year IN ({oot}) THEN 'oot'
            WHEN ('0x' || left(md5(loan_number), 8))::UBIGINT % 100 < {test_pct}
                THEN 'test'
            ELSE 'train'
        END AS sample,
        -- Derived features, as of the snapshot.
        year(acquisition_date) AS acquisition_year,
        date_diff('month', date_trunc('month', note_date), snapshot_date)
            AS months_on_book,
        date_diff('month', snapshot_date, date_trunc('month', maturity_date_current))
            AS months_to_maturity,
        upb_current / original_upb AS upb_pct_original,
        {", ".join(f'"{c}"' for c in STATIC_FEATURES + PERIOD_FEATURES)},
        months_delinquent_last_12,
        months_modified_last_12
    FROM candidates
    ORDER BY snapshot_year, loan_number
    """


def build_snapshots(con: duckdb.DuckDBPyConnection, cfg: dict) -> None:
    [(data_end,)] = con.execute(
        f"SELECT max(reporting_period_date) FROM {PERFORMANCE_TABLE}"
    ).fetchall()
    con.execute(
        f"CREATE OR REPLACE TABLE {SNAPSHOTS_TABLE} AS "
        f"{snapshots_sql(cfg, str(data_end))}"
    )


def waterfall(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Candidates and exclusions by snapshot year (wide: one column each)."""
    return (
        con.sql(
            f"""SELECT snapshot_year,
                coalesce(exclusion_reason, 'Eligible') AS status,
                count(*) AS n
            FROM {SNAPSHOTS_TABLE} GROUP BY ALL"""
        )
        .pl()
        .pivot(on="status", index="snapshot_year", values="n")
        .fill_null(0)
        .sort("snapshot_year")
        .with_columns(Candidates=pl.sum_horizontal(pl.exclude("snapshot_year")))
    )


def default_rates(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Eligible observations, defaults and default rate by snapshot year."""
    return con.sql(
        f"""SELECT snapshot_year,
            any_value(sample) FILTER (sample = 'oot') IS NOT NULL AS oot,
            count(*) AS observations,
            count(*) FILTER (default_12m) AS defaults,
            count(*) FILTER (covid_forbearance) AS covid_forbearance_defaults,
            round(100 * avg(default_12m::INT), 3) AS default_rate_pct,
            round(100 * avg((default_12m AND NOT covid_forbearance)::INT), 3)
                AS default_rate_ex_covid_pct,
            count(*) FILTER (exited_in_horizon) AS exited_in_horizon
        FROM {SNAPSHOTS_TABLE}
        WHERE exclusion_reason IS NULL
        GROUP BY snapshot_year ORDER BY snapshot_year"""
    ).pl()


def sample_summary(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    return con.sql(
        f"""SELECT sample,
            count(DISTINCT loan_number) AS loans,
            count(*) AS observations,
            count(*) FILTER (default_12m) AS defaults,
            round(100 * avg(default_12m::INT), 3) AS default_rate_pct
        FROM {SNAPSHOTS_TABLE}
        WHERE exclusion_reason IS NULL
        GROUP BY sample ORDER BY sample"""
    ).pl()


def main() -> None:
    cfg = load_config()
    out_dir = (
        repo_path(cfg["modeling"]["report_dir"]) / Path(cfg["data"]["raw_file"]).stem
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(repo_path(cfg["data"]["database"]))) as con:
        build_snapshots(con, cfg["modeling"])
        tables = {
            "waterfall": waterfall(con),
            "default_rates": default_rates(con),
            "samples": sample_summary(con),
        }
    for name, df in tables.items():
        df.write_csv(out_dir / f"{name}.csv")
    with pl.Config(tbl_rows=-1, tbl_width_chars=160):
        for name, df in tables.items():
            print(name)
            print(df)
    print(f"Wrote {out_dir.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
