import itertools
import math

import polars as pl
import pytest

from mf_scorecard.rating_scale import (
    GRADES,
    PD_FLOOR,
    PERFORMING,
    assign_grades,
    representative_pd,
    scale_table,
)


def test_intervals_are_contiguous_and_cover_zero_to_one():
    assert [g.grade for g in GRADES] == list(range(1, 11))
    assert PERFORMING[0].pd_min == 0.0
    assert PERFORMING[-1].pd_max == 1.0
    for lower, upper in itertools.pairwise(PERFORMING):
        assert lower.pd_max == upper.pd_min
        assert lower.pd_min < lower.pd_max


def test_worst_four_grades_are_regulatory_categories():
    assert [g.category for g in GRADES[-4:]] == [
        "Special Mention",
        "Substandard",
        "Doubtful",
        "Loss",
    ]
    assert all(g.category == "Pass" for g in GRADES[:-4])
    assert [g.grade for g in GRADES if g.is_default] == [9, 10]


def test_assign_grades_boundaries_go_to_worse_grade():
    pd = pl.Series([0.0, 0.0004999, 0.0005, 0.0019, 0.02, 0.0999, 0.1, 0.99])
    assert assign_grades(pd).to_list() == [1, 1, 2, 3, 7, 7, 8, 8]


@pytest.mark.parametrize("bad", [[-0.01], [1.0], [None]])
def test_assign_grades_rejects_invalid_pd(bad):
    with pytest.raises(ValueError):
        assign_grades(pl.Series(bad, dtype=pl.Float64))


def test_representative_pd_is_in_its_grade():
    reps = representative_pd(pl.Series(range(1, 11)))
    for g, rep in zip(GRADES, reps):
        if g.is_default:
            assert rep == 1.0
        else:
            assert max(g.pd_min, PD_FLOOR) <= rep < g.pd_max
    assert math.isclose(reps[0], math.sqrt(PD_FLOOR * 0.0005))
    # Representative PDs map back to their own grade.
    assert assign_grades(reps[:8]).to_list() == list(range(1, 9))


def test_scale_table():
    t = scale_table()
    assert t.height == 10
    assert t.filter(pl.col("grade") >= 9)["pd_min_pct"].null_count() == 2
