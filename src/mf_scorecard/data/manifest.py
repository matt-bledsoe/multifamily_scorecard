"""Record which data file and code built the database.

The manifest is written to ``manifests/<raw file stem>.json`` (committed to
git) and to a ``data_manifest`` table in the database. Models built later can
cite the manifest's file hash to show exactly which data they used.

Run after the load and stage steps:
``uv run python -m mf_scorecard.data.manifest``
"""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import duckdb

from mf_scorecard.config import REPO_ROOT, load_config, repo_path
from mf_scorecard.data.load import RAW_TABLE
from mf_scorecard.data.stage import STAGE_TABLE

MANIFEST_TABLE = "data_manifest"


def sha256(path: Path, chunk_size: int = 1 << 24) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def release_from_filename(path: Path) -> str | None:
    """``..._202606.csv`` -> ``2026-06``; None if the name has no YYYYMM."""
    m = re.search(r"_(\d{4})(\d{2})\.csv$", path.name)
    return f"{m[1]}-{m[2]}" if m else None


def git_state(repo: Path = REPO_ROOT, ignore: tuple[str, ...] = ()) -> dict:
    """Current commit, and whether the code has uncommitted changes.

    ``ignore`` lists repo-relative paths that don't count as code changes,
    such as the manifest directory this step itself writes to.
    """

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()

    excludes = [f":(exclude){p}" for p in ignore]
    try:
        return {
            "commit": git("rev-parse", "HEAD"),
            "uncommitted_changes": bool(
                git("status", "--porcelain", "--", ".", *excludes)
            ),
        }
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "uncommitted_changes": None}


def table_stats(con: duckdb.DuckDBPyConnection, table: str) -> dict:
    [(n_rows, n_loans, first, last)] = con.execute(
        f"SELECT count(*), count(DISTINCT loan_number), "
        f"min(reporting_period_date), max(reporting_period_date) FROM {table}"
    ).fetchall()
    return {
        "n_rows": n_rows,
        "n_loans": n_loans,
        "first_reporting_period": str(first) if first else None,
        "last_reporting_period": str(last) if last else None,
    }


def build_manifest(
    con: duckdb.DuckDBPyConnection,
    data_file: Path,
    git_ignore: tuple[str, ...] = (),
) -> dict:
    raw = table_stats(con, RAW_TABLE)
    stage = table_stats(con, STAGE_TABLE)
    if raw != stage:
        raise ValueError(
            f"{STAGE_TABLE} does not match {RAW_TABLE}; rerun the stage step.\n"
            f"  raw:   {raw}\n  stage: {stage}"
        )
    schema_file = files("mf_scorecard.data") / "mflpd_schema.csv"
    return {
        "source_file": data_file.name,
        "release": release_from_filename(data_file),
        "sha256": sha256(data_file),
        "file_size_bytes": data_file.stat().st_size,
        "schema_sha256": hashlib.sha256(schema_file.read_bytes()).hexdigest(),
        "tables": {RAW_TABLE: raw, STAGE_TABLE: stage},
        "code": git_state(ignore=git_ignore),
        "duckdb_version": duckdb.__version__,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def write_manifest(manifest: dict, manifest_dir: Path) -> Path:
    """Write the JSON manifest, refusing to overwrite one for a different file.

    Rebuilding from the same file replaces the manifest (new build time, code
    commit). A different hash under the same file name means the source data
    changed without being renamed, which must be resolved by hand.
    """
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"{Path(manifest['source_file']).stem}.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["sha256"] != manifest["sha256"]:
            raise ValueError(
                f"{manifest['source_file']} has changed since {path.name} was "
                f"written (sha256 {previous['sha256'][:12]}… -> "
                f"{manifest['sha256'][:12]}…). Rename the new file or delete "
                f"the old manifest deliberately."
            )
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def store_manifest(con: duckdb.DuckDBPyConnection, manifest: dict) -> None:
    """Keep the manifest in the database so it describes its own contents."""
    con.execute(
        f"CREATE OR REPLACE TABLE {MANIFEST_TABLE} AS "
        "SELECT ?::JSON AS manifest, ? AS sha256, ? AS release",
        [json.dumps(manifest), manifest["sha256"], manifest["release"]],
    )


def main() -> None:
    cfg = load_config()["data"]
    data_file = repo_path(cfg["raw_file"])
    with duckdb.connect(str(repo_path(cfg["database"]))) as con:
        manifest = build_manifest(con, data_file, git_ignore=(cfg["manifest_dir"],))
        path = write_manifest(manifest, repo_path(cfg["manifest_dir"]))
        store_manifest(con, manifest)
    print(f"Wrote {path.relative_to(REPO_ROOT)}")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
