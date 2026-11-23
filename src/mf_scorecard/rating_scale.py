"""The 10-grade rating scale: PD intervals and regulatory categories.

Grades 1-8 are for performing loans and are assigned by the model from its
one-year through-the-cycle PD. Grades 9 and 10 are default grades: a
defaulted loan has a PD of 100%, and whether it is Doubtful or Loss depends
on the expected recovery, which is a credit judgement, not a model output.

Each performing grade covers a PD interval ``[pd_min, pd_max)``. The
intervals roughly double from grade to grade, so a one-grade move means
about the same relative change in risk anywhere on the scale. The
representative PD of a grade is the geometric midpoint of its interval;
it is the PD that should be used for anything computed from a grade
(expected loss, capital, portfolio averages), rather than the grade number.
"""

import math
from dataclasses import dataclass

import polars as pl

# Lowest PD the model may assign (the Basel / US advanced-approaches floor).
PD_FLOOR = 0.0003


@dataclass(frozen=True)
class Grade:
    grade: int
    category: str
    pd_min: float
    pd_max: float

    @property
    def is_default(self) -> bool:
        return self.pd_min >= 1.0

    @property
    def representative_pd(self) -> float:
        if self.is_default:
            return 1.0
        return math.sqrt(max(self.pd_min, PD_FLOOR) * self.pd_max)


GRADES = (
    Grade(1, "Pass", 0.0, 0.0005),
    Grade(2, "Pass", 0.0005, 0.0010),
    Grade(3, "Pass", 0.0010, 0.0020),
    Grade(4, "Pass", 0.0020, 0.0040),
    Grade(5, "Pass", 0.0040, 0.0080),
    Grade(6, "Pass", 0.0080, 0.0200),
    Grade(7, "Special Mention", 0.0200, 0.1000),
    Grade(8, "Substandard", 0.1000, 1.0),
    Grade(9, "Doubtful", 1.0, 1.0),
    Grade(10, "Loss", 1.0, 1.0),
)

PERFORMING = tuple(g for g in GRADES if not g.is_default)
# Upper PD bounds of grades 1-7: the cut points between performing grades.
BREAKS = [g.pd_max for g in PERFORMING[:-1]]


def assign_grades(pd: pl.Series) -> pl.Series:
    """Performing grade (1-8) for each one-year PD, given as a fraction.

    A PD exactly on a boundary goes to the worse grade. Raises if any PD is
    missing or outside [0, 1): a PD of 1 means default, which the model does
    not assign.
    """
    if pd.null_count() or ((pd < 0) | (pd >= 1)).any():
        raise ValueError("PDs must be non-missing and in [0, 1)")
    return (pl.Series(BREAKS).search_sorted(pd, side="right").cast(pl.Int8) + 1).alias(
        "grade"
    )


def representative_pd(grade: pl.Series) -> pl.Series:
    """The representative PD of each grade (1-10)."""
    pds = {g.grade: g.representative_pd for g in GRADES}
    return grade.replace_strict(pds, return_dtype=pl.Float64).alias("representative_pd")


def scale_table() -> pl.DataFrame:
    """The scale as a table, with PDs in percent."""
    return pl.DataFrame(
        {
            "grade": [g.grade for g in GRADES],
            "category": [g.category for g in GRADES],
            "pd_min_pct": [None if g.is_default else 100 * g.pd_min for g in GRADES],
            "pd_max_pct": [None if g.is_default else 100 * g.pd_max for g in GRADES],
            "representative_pd_pct": [100 * g.representative_pd for g in GRADES],
        }
    )
