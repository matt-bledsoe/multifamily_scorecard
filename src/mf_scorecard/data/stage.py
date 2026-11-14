"""Build the staged MFLPD table from the raw table.

The raw table keeps values exactly as Fannie Mae publishes them. Staging
converts text columns to the analytic type given by ``dtype`` in
``mflpd_schema.csv``:

- currency text (``$1,234.56``, negatives as ``($1,234.56)``) -> DOUBLE
- ``Y``/``N`` flags -> BOOLEAN
- numeric text -> INTEGER, after mapping known placeholders to NULL

Casts are strict: a value in an unexpected format raises an error instead of
silently becoming NULL, so format changes in a new release are caught here.

Run with: ``uv run python -m mf_scorecard.data.stage``
"""

import duckdb

from mf_scorecard.config import load_config, repo_path
from mf_scorecard.data.load import RAW_TABLE, read_schema

STAGE_TABLE = "mflpd_stage"

# Placeholder text that means "not applicable" for a single value.
NULL_PLACEHOLDERS = {
    # Loans on more than one property report this instead of a year.
    "year_built": ["Multiple Properties"],
}

DUCKDB_TYPES = {"Float64": "DOUBLE", "Int64": "INTEGER", "Boolean": "BOOLEAN"}


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def column_expr(name: str, raw_type: str, dtype: str, is_currency: bool) -> str:
    """SQL expression that converts one raw column to its staged type."""
    col = f'"{name}"'
    if raw_type != "VARCHAR" or dtype == "String":
        return col

    if name in NULL_PLACEHOLDERS:
        placeholders = ", ".join(_sql_str(v) for v in NULL_PLACEHOLDERS[name])
        col = f"CASE WHEN {col} IN ({placeholders}) THEN NULL ELSE {col} END"

    if is_currency:
        # ($1,234.56) -> -1234.56
        digits = f"regexp_replace({col}, '[$,()]', '', 'g')"
        expr = (
            f"CASE WHEN starts_with({col}, '(') THEN -1 ELSE 1 END "
            f"* CAST({digits} AS DOUBLE)"
        )
    elif dtype == "Boolean":
        expr = (
            f"CASE WHEN {col} IS NULL THEN NULL "
            f"WHEN {col} = 'Y' THEN true WHEN {col} = 'N' THEN false "
            f"ELSE error('Unexpected {name} flag: ' || {col}) END"
        )
    elif dtype in DUCKDB_TYPES:
        expr = f"CAST({col} AS {DUCKDB_TYPES[dtype]})"
    else:
        raise ValueError(f"No staging rule for {name}: {raw_type} -> {dtype}")
    return f'{expr} AS "{name}"'


def stage_sql() -> str:
    exprs = [
        column_expr(r["name"], r["type"], r["dtype"], bool(r["is_CURRENCY"]))
        for r in read_schema().iter_rows(named=True)
    ]
    return "SELECT\n  " + ",\n  ".join(exprs) + f"\nFROM {RAW_TABLE}"


def build_stage(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"CREATE OR REPLACE TABLE {STAGE_TABLE} AS {stage_sql()}")


def main() -> None:
    database = repo_path(load_config()["data"]["database"])
    with duckdb.connect(str(database)) as con:
        build_stage(con)
        print(con.sql(f"DESCRIBE {STAGE_TABLE}"))
        print(con.sql(f"SELECT count(*) AS n_rows FROM {STAGE_TABLE}"))


if __name__ == "__main__":
    main()
