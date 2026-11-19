import matplotlib.colors as mcolors
import pytest

import insight_chart as ic

X = ["Jan", "Feb", "Mar", "Apr"]
DATA = {"North": [1200, 1150, 1040, 980], "South": [900, 940, 960, 1010], "West": [700, 720, 690, 710]}


def test_headline_states_direction_and_size():
    assert ic.headline(ic.Finding("North", 1200, 980), "orders", "in Q1") == "North orders fell 18% in Q1"
    assert ic.headline(ic.Finding("South", 900, 1010), "orders", "since January") == "South orders rose 12% since January"
    assert ic.headline(ic.Finding("West", 700, 703), "orders", "this quarter") == "West orders held steady this quarter"


def test_pct_change_from_zero_is_rejected():
    with pytest.raises(ValueError):
        ic.Finding("x", 0, 5).pct_change


def test_chart_highlights_one_series_and_titles_the_finding(tmp_path):
    out = tmp_path / "chart.png"
    fig, ax, f = ic.insight_chart(X, DATA, focus="North", metric="orders", period="Jan to Apr",
                                  source="Order system extract", path=str(out))
    assert out.exists() and out.stat().st_size > 10_000
    assert ax.get_title(loc="left") == "North orders fell 18% Jan to Apr"
    colours = [mcolors.to_hex(l.get_color()).upper() for l in ax.get_lines()]
    assert colours.count(ic.FOCUS.upper()) == 1
    assert colours.count(ic.CONTEXT.upper()) == 2
    assert ax.get_lines()[-1].get_linewidth() > ax.get_lines()[0].get_linewidth()   # focus drawn last, thicker
    assert ax.get_legend() is None                    # direct labels instead of a legend
    assert not ax.spines["top"].get_visible() and not ax.spines["right"].get_visible()
    labels = [t.get_text() for t in ax.texts]
    assert "North" in labels and "980 (-18%)" in labels
    assert any(t.get_text().startswith("Source:") for t in fig.texts)


def test_bad_inputs():
    with pytest.raises(KeyError):
        ic.insight_chart(X, DATA, focus="East", metric="orders", period="")
    with pytest.raises(ValueError):
        ic.insight_chart(X, {"North": [1, 2]}, focus="North", metric="orders", period="")
