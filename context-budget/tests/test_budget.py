import pytest

from budget import BudgetError, Item, Section, plan


def words(text: str) -> int:
    return len(text.split())


def turns(n, size=10):
    return [Item(" ".join(["w"] * size), order=i) for i in range(n)]


def docs(scores, size=20):
    return [Item(" ".join(["d"] * size), score=s) for s in scores]


SYSTEM = "s " * 30          # 30 tokens


def test_output_is_reserved_and_fixed_parts_are_whole():
    p = plan(window=200, output_reserve=50, fixed=[SYSTEM, "question " * 10],
             flexible=[Section("history", turns(20), keep="newest")], count=words)
    assert p.fixed_tokens == 40
    assert p.prompt_tokens <= 150 and p.headroom >= 0


def test_history_keeps_newest_turns_in_chronological_order():
    p = plan(200, 50, [SYSTEM], [Section("history", turns(20), keep="newest")], words)
    kept = [i.order for i in p.sections["history"]]
    assert kept == list(range(8, 20))                 # 120 free tokens / 10 per turn = 12 newest
    assert p.dropped["history"] == 8


def test_retrieved_passages_keep_highest_scores():
    p = plan(150, 50, [SYSTEM], [Section("docs", docs([0.2, 0.9, 0.5, 0.8, 0.1, 0.7]), keep="best")], words)
    assert sorted(i.score for i in p.sections["docs"]) == [0.7, 0.8, 0.9]   # 70 free / 20 each = 3


def test_weights_split_space_and_minimums_are_guaranteed():
    hist = Section("history", turns(30), weight=1, min_tokens=20, keep="newest")
    ctx = Section("docs", docs([0.9] * 30), weight=3, keep="best")
    p = plan(250, 50, [SYSTEM], [hist, ctx], words)          # 170 free: history 20 + 150/4, docs 3/4
    assert p.used["history"] >= 20
    assert p.used["docs"] > p.used["history"]
    assert p.prompt_tokens <= 200


def test_section_maximum_is_respected_and_spare_goes_elsewhere():
    hist = Section("history", turns(30), weight=1, max_tokens=30, keep="newest")
    ctx = Section("docs", docs([0.5] * 30, size=10), weight=1, keep="best")
    p = plan(250, 50, [SYSTEM], [hist, ctx], words)
    assert p.used["history"] == 30
    assert p.used["docs"] >= 130                              # gets what history could not use


def test_per_message_overhead_is_counted():
    p = plan(200, 50, [SYSTEM], [Section("history", turns(20), keep="newest")], words, per_message_overhead=3)
    assert p.fixed_tokens == 33
    assert p.used["history"] % 13 == 0 and p.used["history"] <= 117


def test_errors_when_fixed_content_or_minimums_do_not_fit():
    with pytest.raises(BudgetError):
        plan(100, 50, ["x " * 60], [], words)
    with pytest.raises(BudgetError):
        plan(100, 50, [SYSTEM], [Section("a", [], min_tokens=30)], words)
    with pytest.raises(BudgetError):
        plan(100, 100, [SYSTEM], [], words)


def test_unknown_keep_mode_rejected():
    with pytest.raises(ValueError):
        plan(200, 50, [SYSTEM], [Section("x", docs([0.1]), keep="random")], words)
