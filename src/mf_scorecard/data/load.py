"""Load the raw MFLPD CSV into a persistent DuckDB table.

Run with: ``uv run python -m mf_scorecard.data.load``
"""

import csv
from importlib.resources import files
from pathlib import Path

import duckdb
import polars as pl

from mf_scorecard.config import load_config, repo_path

RAW_TABLE = "mflpd_raw"


def read_schema() -> pl.DataFrame:
    """Column metadata: FNMA header name -> snake_case name and DuckDB type."""
    schema_file = files("mf_scorecard.data") / "mflpd_schema.csv"
    # FNMA headers can carry stray whitespace (e.g. "Transaction ID "), so
    # match on stripped names.
    return pl.read_csv(schema_file.read_bytes()).with_columns(
        pl.col("fnma_name").str.strip_chars()
    )


def read_header(data_file: Path) -> list[str]:
    with open(data_file, newline="", encoding="utf-8-sig") as f:
        return [name.strip() for name in next(csv.reader(f))]


def column_types(data_file: Path, schema: pl.DataFrame) -> dict[str, str]:
    """Map each column in the file (in file order) to its name and type.

    Raises if the file's header and the schema don't match, which is the
    signal to update ``mflpd_schema.csv`` for a new release.
    """
    header = read_header(data_file)
    known = set(schema["fnma_name"])
    missing_from_schema = [c for c in header if c not in known]
    missing_from_file = sorted(known - set(header))
    if missing_from_schema or missing_from_file:
        raise ValueError(
            "MFLPD header does not match mflpd_schema.csv.\n"
            f"  In file, not schema: {missing_from_schema}\n"
            f"  In schema, not file: {missing_from_file}"
        )
    lookup = {row["fnma_name"]: row for row in schema.iter_rows(named=True)}
    return {lookup[c]["name"]: lookup[c]["type"] for c in header}


def load_raw(data_file: Path, database: Path) -> None:
    types = column_types(data_file, read_schema())
    database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database)) as con:
        con.execute(
            f"CREATE OR REPLACE TABLE {RAW_TABLE} AS "
            "SELECT * FROM read_csv(?, header = true, columns = ?)",
            [str(data_file), types],
        )
        print(con.sql(f"DESCRIBE {RAW_TABLE}"))
        print(con.sql(f"SELECT count(*) AS n_rows FROM {RAW_TABLE}"))


def main() -> None:
    cfg = load_config()["data"]
    load_raw(repo_path(cfg["raw_file"]), repo_path(cfg["database"]))


if __name__ == "__main__":
    main()
