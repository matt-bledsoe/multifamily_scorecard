import json
from pathlib import Path

import duckdb
import pytest

from mf_scorecard.data.load import RAW_TABLE
from mf_scorecard.data.manifest import (
    MANIFEST_TABLE,
    build_manifest,
    release_from_filename,
    sha256,
    store_manifest,
    write_manifest,
)
from mf_scorecard.data.stage import STAGE_TABLE


@pytest.fixture
def con():
    con = duckdb.connect()
    for table in (RAW_TABLE, STAGE_TABLE):
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM (VALUES "
            "('001', DATE '2020-01-31'), ('001', DATE '2020-02-29'), "
            "('002', DATE '2020-02-29')) t(loan_number, reporting_period_date)"
        )
    yield con
    con.close()


@pytest.fixture
def data_file(tmp_path):
    f = tmp_path / "FNMA_MF_Loan_Performance_Data_202606.csv"
    f.write_text("a,b\n1,2\n")
    return f


def test_release_from_filename():
    assert release_from_filename(Path("X_Data_202606.csv")) == "2026-06"
    assert release_from_filename(Path("X_Data__202403.csv")) == "2024-03"
    assert release_from_filename(Path("no_date.csv")) is None


def test_sha256_reads_in_chunks(data_file):
    assert sha256(data_file, chunk_size=3) == sha256(data_file)


def test_build_manifest(con, data_file):
    m = build_manifest(con, data_file)
    assert m["release"] == "2026-06"
    assert m["sha256"] == sha256(data_file)
    assert m["tables"][RAW_TABLE] == {
        "n_rows": 3,
        "n_loans": 2,
        "first_reporting_period": "2020-01-31",
        "last_reporting_period": "2020-02-29",
    }


def test_stage_out_of_sync_raises(con, data_file):
    con.execute(f"DELETE FROM {STAGE_TABLE} WHERE loan_number = '002'")
    with pytest.raises(ValueError, match="rerun the stage step"):
        build_manifest(con, data_file)


def test_write_manifest_rejects_changed_file(con, data_file, tmp_path):
    out = tmp_path / "manifests"
    path = write_manifest(build_manifest(con, data_file), out)
    assert json.loads(path.read_text())["release"] == "2026-06"

    # Same file again: allowed (overwrites).
    write_manifest(build_manifest(con, data_file), out)

    # Same name, different contents: refused.
    data_file.write_text("a,b\n1,3\n")
    with pytest.raises(ValueError, match="has changed"):
        write_manifest(build_manifest(con, data_file), out)


def test_store_manifest(con, data_file):
    m = build_manifest(con, data_file)
    store_manifest(con, m)
    sha, release = con.execute(
        f"SELECT sha256, release FROM {MANIFEST_TABLE}"
    ).fetchone()
    assert (sha, release) == (m["sha256"], "2026-06")
