"""AI vs AI tournament with fair seating and the metrics for the evaluation slide.

    python -m talat.tournament --agents greedy,paranoid,mcts --rounds 10 --time 1.0
    python -m talat.tournament --agents greedy,maxn,mcts --rounds 10 --workers 4

One round plays all 6 seat orders of the three agents, so every agent plays
every seat equally often (moving first is not an advantage for anyone).
Results go to results/<name>_games.csv (one row per agent per game) and
results/<name>_summary.csv, and a summary table is printed.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import multiprocessing
import os
import statistics
import time
from pathlib import Path

from talat.ai import AGENTS, make_agent
from talat.engine import PLAYERS, apply, end_reason, is_terminal, new_game, score_parts, winners

SEAT_ORDERS = list(itertools.permutations(range(3)))   # which agent sits in P1, P2, P3


def labels_for(names: list[str]) -> list[str]:
    """Unique labels, e.g. greedy,greedy,mcts -> greedy-1, greedy-2, mcts."""
    return [f"{n}-{names[:i + 1].count(n)}" if names.count(n) > 1 else n for i, n in enumerate(names)]


def play_one(task: tuple) -> list[dict]:
    """Play one game and return one result row per agent."""
    game, order, names, labels, time_limit, seed = task
    seat_agent = dict(zip(PLAYERS, order))                       # seat -> agent index
    agents = {p: make_agent(names[i], seed=seed * 1_000_000 + game * 10 + p) for p, i in seat_agent.items()}
    moves = {p: 0 for p in PLAYERS}
    times: dict[int, list[float]] = {p: [] for p in PLAYERS}
    effort = {p: 0 for p in PLAYERS}
    unit = {p: "" for p in PLAYERS}

    state = new_game()
    while not is_terminal(state):
        p = state.to_move
        start = time.perf_counter()
        action = agents[p].choose_action(state, p, time_limit=time_limit)
        elapsed = time.perf_counter() - start
        if state.phase == "play":          # setup placements aren't part of the metrics
            moves[p] += 1
            times[p].append(elapsed)
            stats = agents[p].last_stats
            if "rollouts" in stats:
                effort[p] += stats["rollouts"]
                unit[p] = "rollouts"
            elif "nodes" in stats:
                effort[p] += stats["nodes"]
                unit[p] = "nodes"
        state = apply(state, action)

    parts, win = score_parts(state), winners(state)
    seating = "/".join(labels[seat_agent[p]] for p in PLAYERS)
    return [
        {
            "game": game,
            "seating": seating,
            "agent": labels[seat_agent[p]],
            "seat": p,
            "score": sum(parts[p]),
            "capture_points": parts[p][0],
            "line_points": parts[p][1],
            "win_share": round(1 / len(win), 4) if p in win else 0,
            "sole_win": int(win == [p]),
            "moves": moves[p],
            "time_mean": round(statistics.mean(times[p]), 4) if times[p] else 0,
            "time_max": round(max(times[p]), 4) if times[p] else 0,
            "effort_per_move": round(effort[p] / moves[p], 1) if moves[p] else 0,
            "effort_unit": unit[p],
            "actions": state.action_count,
            "end_reason": end_reason(state),
        }
        for p in PLAYERS
    ]


def summarize(rows: list[dict], labels: list[str]) -> list[dict]:
    out = []
    for label in labels:
        mine = [r for r in rows if r["agent"] == label]
        games = len(mine)
        all_moves = sum(r["moves"] for r in mine)
        summary = {
            "agent": label,
            "games": games,
            "win_rate_%": round(100 * sum(r["win_share"] for r in mine) / games, 1),
            "sole_wins": sum(r["sole_win"] for r in mine),
            "avg_score": round(statistics.mean(r["score"] for r in mine), 1),
            "avg_capture_points": round(statistics.mean(r["capture_points"] for r in mine), 1),
            "avg_line_points": round(statistics.mean(r["line_points"] for r in mine), 1),
            "time_per_move_s": round(sum(r["time_mean"] * r["moves"] for r in mine) / all_moves, 3) if all_moves else 0,
            "worst_move_s": max(r["time_max"] for r in mine),
            "effort_per_move": round(sum(r["effort_per_move"] * r["moves"] for r in mine) / all_moves, 1) if all_moves else 0,
            "effort_unit": next((r["effort_unit"] for r in mine if r["effort_unit"]), "-"),
        }
        for seat in PLAYERS:
            at_seat = [r for r in mine if r["seat"] == seat]
            summary[f"win_%_as_P{seat}"] = round(100 * sum(r["win_share"] for r in at_seat) / len(at_seat), 1) if at_seat else 0
        out.append(summary)
    return out


def format_table(summary: list[dict]) -> str:
    cols = [
        ("Agent", "agent", "{}"), ("Games", "games", "{}"), ("Win %", "win_rate_%", "{:.1f}"),
        ("Avg score", "avg_score", "{:.1f}"), ("Captures", "avg_capture_points", "{:.1f}"),
        ("Line pts", "avg_line_points", "{:.1f}"), ("s/move", "time_per_move_s", "{:.3f}"),
        ("Worst s", "worst_move_s", "{:.3f}"), ("Effort/move", "effort_per_move", "{:.0f}"),
        ("Unit", "effort_unit", "{}"), ("Win% P1", "win_%_as_P1", "{:.0f}"),
        ("P2", "win_%_as_P2", "{:.0f}"), ("P3", "win_%_as_P3", "{:.0f}"),
    ]
    cells = [[head for head, _, _ in cols]] + [[fmt.format(s[key]) for _, key, fmt in cols] for s in summary]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    lines = ["  ".join(c.rjust(w) if i else c.ljust(w) for i, (c, w) in enumerate(zip(row, widths))) for row in cells]
    lines.insert(1, "-" * len(lines[0]))
    return "\n".join(lines)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(names: list[str], rounds: int, time_limit: float | None, workers: int, seed: int = 0,
        out_dir: Path | None = Path("results"), progress: bool = True) -> tuple[list[dict], list[dict]]:
    """Play rounds x 6 games. Returns (per-game rows, per-agent summary)."""
    labels = labels_for(names)
    tasks = [(r * 6 + i, order, names, labels, time_limit, seed)
             for r in range(rounds) for i, order in enumerate(SEAT_ORDERS)]
    rows: list[dict] = []
    started = time.time()
    if workers > 1:
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            for done, game_rows in enumerate(pool.imap_unordered(play_one, tasks), 1):
                rows.extend(game_rows)
                if progress:
                    print(f"  {done}/{len(tasks)} games ({time.time() - started:.0f}s)", flush=True)
    else:
        for done, task in enumerate(tasks, 1):
            rows.extend(play_one(task))
            if progress:
                print(f"  {done}/{len(tasks)} games ({time.time() - started:.0f}s)", flush=True)
    rows.sort(key=lambda r: (r["game"], r["seat"]))
    summary = summarize(rows, labels)
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        name = "_vs_".join(labels) + (f"_{time_limit}s" if time_limit else "_nolimit")
        write_csv(out_dir / f"{name}_games.csv", rows)
        write_csv(out_dir / f"{name}_summary.csv", summary)
    return rows, summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Play a TALAT AI tournament with all 6 seat orders.")
    parser.add_argument("--agents", default="greedy,paranoid,mcts", help=f"three of: {', '.join(AGENTS)}")
    parser.add_argument("--rounds", type=int, default=10, help="rounds of 6 games (one per seat order)")
    parser.add_argument("--time", type=float, default=1.0, help="seconds per move for the searching agents")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1),
                        help="games played in parallel (more than half your cores can stretch move times)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="results", help="folder for the CSV files")
    args = parser.parse_args(argv)

    names = [n.strip().lower() for n in args.agents.split(",")]
    if len(names) != 3 or any(n not in AGENTS for n in names):
        parser.error(f"--agents needs three of: {', '.join(AGENTS)}")
    print(f"{args.rounds * 6} games: {', '.join(names)} at {args.time}s per move, {args.workers} workers")
    rows, summary = run(names, args.rounds, args.time, args.workers, args.seed, Path(args.out))
    ends = {reason: sum(1 for r in rows if r["seat"] == 1 and r["end_reason"] == reason)
            for reason in {r["end_reason"] for r in rows}}
    print()
    print(format_table(summary))
    print(f"\nEndings: {ends}.  CSV files saved in {args.out}/")


if __name__ == "__main__":
    main()
