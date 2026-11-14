"""Shared matplotlib styling for report figures.

Colours follow a single-hue scheme: one series blue for data, a light gray
for de-emphasised marks, and recessive hairline grid and axes. Values in the
reports are also given in tables, so no chart is the only way to read a
number.
"""

import matplotlib.pyplot as plt
import polars as pl
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter


def markdown_table(
    df: pl.DataFrame,
    decimals: int = 1,
    no_separator: tuple[str, ...] = (),
) -> str:
    """Format a DataFrame as a Markdown table for Quarto reports.

    Integers get thousands separators (except columns in ``no_separator``,
    such as years), floats are rounded to ``decimals``, blanks show as an
    en dash, and numeric columns are right-aligned.
    """

    def fmt(value, dtype, column: str) -> str:
        if value is None:
            return "–"
        if dtype.is_integer():
            return str(value) if column in no_separator else f"{value:,}"
        if dtype.is_float():
            return f"{value:,.{decimals}f}"
        return str(value).replace("|", "\\|")

    header = "| " + " | ".join(df.columns) + " |"
    align = (
        "|"
        + "|".join("---:" if dtype.is_numeric() else ":---" for dtype in df.dtypes)
        + "|"
    )
    rows = [
        "| "
        + " | ".join(
            fmt(v, dtype, col) for v, dtype, col in zip(row, df.dtypes, df.columns)
        )
        + " |"
        for row in df.iter_rows()
    ]
    return "\n".join([header, align, *rows])


COLORS = {
    "surface": "#fcfcfb",
    "ink": "#0b0b0b",
    "ink_secondary": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "series": "#2a78d6",  # 4.3:1 on surface
    "deemphasis": "#c3c2b7",  # always direct-labelled where used
}


def apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": COLORS["surface"],
            "axes.facecolor": COLORS["surface"],
            "savefig.facecolor": COLORS["surface"],
            "figure.dpi": 110,
            "font.family": "sans-serif",
            "font.size": 10,
            "text.color": COLORS["ink"],
            "axes.labelcolor": COLORS["ink_secondary"],
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 10,
            "axes.edgecolor": COLORS["axis"],
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": COLORS["grid"],
            "grid.linewidth": 0.6,
            "grid.linestyle": "-",
            "xtick.color": COLORS["muted"],
            "ytick.color": COLORS["muted"],
            "xtick.labelcolor": COLORS["ink_secondary"],
            "ytick.labelcolor": COLORS["ink_secondary"],
            "ytick.left": False,
            "legend.frameon": False,
        }
    )


def thousands(ax: Axes, axis: str = "y") -> None:
    fmt = FuncFormatter(lambda v, _: f"{v:,.0f}")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def percent(ax: Axes, axis: str = "y", decimals: int = 0) -> None:
    fmt = FuncFormatter(lambda v, _: f"{v:.{decimals}f}%")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def columns(
    ax: Axes,
    x: list,
    y: list,
    deemphasise: list[bool] | None = None,
) -> None:
    """Vertical bars, one hue; optionally gray out some bars."""
    deemphasise = deemphasise or [False] * len(x)
    colors = [COLORS["deemphasis"] if d else COLORS["series"] for d in deemphasise]
    # Width < 1 leaves a surface gap between adjacent bars.
    ax.bar(x, y, width=0.8, color=colors, linewidth=0)
    ax.grid(axis="x", visible=False)


def ranked_bars(ax: Axes, labels: list[str], values: list[float]) -> None:
    """Horizontal bars, largest at the top, one hue, value at each bar end."""
    ax.barh(
        labels[::-1], values[::-1], height=0.75, color=COLORS["series"], linewidth=0
    )
    ax.grid(axis="y", visible=False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", length=0)
    ax.set_xticks([])
    ax.grid(axis="x", visible=False)
    top = max(values)
    for label, value in zip(labels, values):
        ax.text(
            value + top * 0.01,
            label,
            f"{value:,.0f}",
            va="center",
            fontsize=9,
            color=COLORS["ink_secondary"],
        )
    ax.set_xlim(0, top * 1.12)


def histogram(ax: Axes, values, bins, xlabel: str) -> None:
    ax.hist(
        values,
        bins=bins,
        color=COLORS["series"],
        edgecolor=COLORS["surface"],
        linewidth=0.6,
    )
    ax.grid(axis="x", visible=False)
    ax.set_xlabel(xlabel)
    thousands(ax)
