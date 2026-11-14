import polars as pl

from mf_scorecard.viz import markdown_table


def test_markdown_table():
    df = pl.DataFrame(
        {
            "Type": ["Multi|family", None],
            "Year": [2008, 2020],
            "Loans": [62889, 309],
            "Rate (%)": [3.171, None],
        }
    )
    assert markdown_table(df, decimals=2, no_separator=("Year",)).splitlines() == [
        "| Type | Year | Loans | Rate (%) |",
        "|:---|---:|---:|---:|",
        "| Multi\\|family | 2008 | 62,889 | 3.17 |",
        "| – | 2020 | 309 | – |",
    ]
