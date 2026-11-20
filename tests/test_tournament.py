import csv

import pytest

from talat.tournament import SEAT_ORDERS, format_table, labels_for, main, run


def test_six_seat_orders_cover_every_seat():
    assert len(SEAT_ORDERS) == 6
    for agent in range(3):
        assert sorted(order.index(agent) for order in SEAT_ORDERS) == [0, 0, 1, 1, 2, 2]


def test_labels_are_unique():
    assert labels_for(["greedy", "greedy", "mcts"]) == ["greedy-1", "greedy-2", "mcts"]
    assert labels_for(["random", "greedy", "mcts"]) == ["random", "greedy", "mcts"]


@pytest.fixture(scope="module")
def small_tournament(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    rows, summary = run(["random", "greedy", "random"], rounds=1, time_limit=None, workers=1,
                        out_dir=out, progress=False)
    return out, rows, summary


def test_every_agent_plays_every_seat_once_per_round(small_tournament):
    _, rows, summary = small_tournament
    assert len(rows) == 6 * 3
    for label in ("random-1", "greedy", "random-2"):
        assert sorted(r["seat"] for r in rows if r["agent"] == label) == [1, 1, 2, 2, 3, 3]
    assert [s["agent"] for s in summary] == ["random-1", "greedy", "random-2"]


def test_win_shares_add_up_to_one_per_game(small_tournament):
    _, rows, summary = small_tournament
    for game in range(6):
        assert sum(r["win_share"] for r in rows if r["game"] == game) == pytest.approx(1)
    assert sum(s["win_rate_%"] for s in summary) == pytest.approx(100, abs=0.2)


def test_scores_split_into_captures_and_lines(small_tournament):
    _, rows, _ = small_tournament
    for r in rows:
        assert r["score"] == r["capture_points"] + r["line_points"]
        assert r["moves"] > 0


def test_effort_units(small_tournament):
    _, _, summary = small_tournament
    units = {s["agent"]: s["effort_unit"] for s in summary}
    assert units == {"random-1": "-", "greedy": "nodes", "random-2": "-"}


def test_csv_files_written(small_tournament):
    out, rows, _ = small_tournament
    games = out / "random-1_vs_greedy_vs_random-2_nolimit_games.csv"
    summary = out / "random-1_vs_greedy_vs_random-2_nolimit_summary.csv"
    assert games.exists() and summary.exists()
    with games.open() as f:
        assert len(list(csv.DictReader(f))) == len(rows)


def test_table_has_a_row_per_agent(small_tournament):
    _, _, summary = small_tournament
    table = format_table(summary)
    assert table.splitlines()[0].startswith("Agent")
    assert len(table.splitlines()) == 2 + 3


def test_parallel_matches_sequential(tmp_path):
    seq, _ = run(["random", "greedy", "random"], 1, None, workers=1, out_dir=None, progress=False)
    par, _ = run(["random", "greedy", "random"], 1, None, workers=2, out_dir=None, progress=False)
    strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("time")} for r in rows]
    assert strip(seq) == strip(par)


def test_command_line(tmp_path, capsys):
    main(["--agents", "random,greedy,random", "--rounds", "1", "--workers", "1", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "Win %" in out and "greedy" in out
    with pytest.raises(SystemExit):
        main(["--agents", "random,greedy"])
