# TALAT: build plan

How to use this file: paste the **Project brief** once at the start of a new chat, then send the steps one at a time ("Do Step 1", "Do Step 2", ...). Finish and test each step before starting the next.

---

## Project brief (paste this first)

> We are building **TALAT**, our CSE 3210 Artificial Intelligence Lab final project (KUET, instructor Waliul Islam Sumon). It is a 3-player, 3-board strategy game based on the board game *Talat* by Bruce Whitehill, with 3 AI agents: **Greedy Best-First**, **Max^n / Paranoid alpha-beta**, and **MCTS with UCB1**.
>
> **Tech:** Python 3.11+. Game engine and AIs are pure Python (standard library only). UI in **Flet**, so the same app runs on desktop and on an Android phone (`flet run --android`, `flet build apk`). Tests with **pytest**.
>
> **Code rules:** type hints, small functions, docstrings only where the logic isn't obvious. The engine never imports UI code. All randomness goes through a seeded `random.Random` so games can be replayed. Every AI exposes the same function: `choose_action(state, player, time_limit) -> Action`.
>
> Follow the **Game rules spec** below exactly. If something is unclear, ask before guessing.

---

## Game rules spec (official rules, with our decisions marked "Decision")

**Players and boards**
- Players: **P1 = White, P2 = Black, P3 = Grey**.
- Three 5×5 boards. Rows 0–4, columns 0–4.
  - **Board A:** P1 top (row 0, moves down) vs P2 bottom (row 4, moves up)
  - **Board B:** P2 top vs P3 bottom
  - **Board C:** P3 top vs P1 bottom
- Each player plays on exactly 2 boards. Row 0 is the top player's **starting line**; row 4 is the bottom player's.

**Towers**
- 9 per player: every combination of size **L (3), M (2), S (1)** and shape **H = hexagon (6 sides), Q = square (4), T = triangle (3)**.
- Rank for tie-breaks: compare (size, sides); L-H is highest.

**1. Setup**
- Players take turns (P1, P2, P3, P1, ...) placing **one** tower on any empty square of **their own** starting lines (2 lines × 5 = 10 squares).
- After 9 placements each, one of each player's squares stays empty.
- Placed towers cannot be moved during setup.
- Decision: AIs place randomly by default (seeded).

**2. Turn**
- P1 starts.
- On your turn you must make exactly one action (a move or a capture) with one of your towers, so you play on one board.
- Actions on frozen boards are not allowed.
- Decision: if a player has no legal action anywhere, they pass.

**3. Move**
- One square **forward**, straight or diagonal, onto an **empty** square.
- No sideways moves, no backward moves, no jumping.
- A tower on the enemy's starting line cannot move any more, but can still capture sideways.

**4. Capture (optional)**
- You may capture an enemy tower that is:
  - straight in front,
  - diagonally in front, or
  - **directly beside** (left or right).
- Your tower moves onto that square. The captured tower goes to your captured pile.
- `can_capture(a, b)` is true if any of these holds:
  - `a.size - b.size == 1` (L takes M, M takes S; L **cannot** take S), or
  - same size and `sides(a) > sides(b)` (H > Q > T), or
  - **David & Goliath:** a is S-T and b is L-H.
- Identical size and shape: no capture. You can never capture your own towers.

**5. Frozen boards and end of game**
- A board is **frozen** when no capture can ever happen on it again. Nobody may act on a frozen board.
- **The game ends when 2 of the 3 boards are frozen.**
- Frozen test. Ignore blocking by other towers: if a capture is still *theoretically* possible, the board is not frozen.
  1. For every top-player tower `t` at `(rt, ct)` and bottom-player tower `u` at `(ru, cu)` on the board where `can_capture(t, u) or can_capture(u, t)`, the pair is **live** if `rt <= ru` and `abs(ct - cu) <= (ru - rt) + 1`.
  2. The board is frozen when no live pair exists.
- Decision: safety limit of 300 actions. Also end the game if all three players pass in a row.

**6. Scoring**
- **+5** for every tower you captured.
- **+3** for every one of your towers standing on an opponent's starting line when the game ends.
- Most points wins.
- Tie: compare each tied player's captured towers sorted by rank, highest first. The higher list wins. If still equal, it's a shared win.

---

## Project layout

```
talat/
  engine.py        # Tower, Board, GameState, Action, setup, legal actions, apply, frozen, scoring
  ai/
    base.py        # Agent interface + RandomAgent
    greedy.py      # AI 1
    maxn.py        # AI 2 (Max^n + Paranoid alpha-beta)
    mcts.py        # AI 3
  cli.py           # text-mode game for quick checks
  tournament.py    # AI vs AI matches and metrics
  app.py           # Flet UI (desktop + phone)
tests/
requirements.txt   # flet, pytest
README.md
```

---

## Steps

### Step 0: Project setup
Create the folder layout above, `requirements.txt` (flet, pytest), a `.venv`, a short `README.md` with run commands, and a `.gitignore`. Initialise git.
**Done when:** `pip install -r requirements.txt` works and `pytest` runs (0 tests is fine).

### Step 1: Engine data model and setup phase
In `engine.py`, create:
- `Tower` (owner, size, shape)
- `Board` (name, top player, bottom player, 5×5 grid)
- `GameState`: 3 boards, phase setup/play, player to move, each player's towers in hand, captured piles, action count, pass counter
- `Action` types: `Place`, `Move`, `Capture`, `Pass`

Also add these functions:
- `new_game()` (no seed: the game itself has no randomness; agents get their own seeded `random.Random`)
- `legal_placements(state, player)`
- `apply(state, action) -> new state`. Use copy-on-apply so the AIs can search safely.

**Tests:**
- Each player gets 9 unique towers.
- Players can only place on their own starting lines.
- Turn order during setup is correct.
- After setup, every player has exactly 1 empty starting square.

### Step 2: Moves and captures
Add `can_capture(a, b)` and `legal_actions(state, player)`. Cover forward and diagonal-forward moves to empty squares, captures in front, diagonally in front and sideways, and correct directions for top and bottom players.

**Tests**, one per rule:
- L takes M, but L cannot take S.
- M takes S.
- Same size: H takes Q and T; Q takes T; T cannot take Q.
- Identical towers can't capture.
- David & Goliath works, and only for S-T against L-H.
- No sideways or backward moves.
- Sideways capture works.
- A tower on the enemy starting line can only capture sideways.
- You can't capture your own towers.

### Step 3: Frozen boards, end of game, scoring
Add `is_frozen(board)`, `is_terminal(state)`, `scores(state)` and `winners(state)` (with the tie-break). `legal_actions` must skip frozen boards, and the pass rule applies when a player has nothing to do.

**Tests:**
- Recreate the 3 frozen-board examples from page 5 of the official rules.
- Passed-each-other towers make a board frozen.
- A David & Goliath threat keeps a board live.
- Scoring with starting-line towers.
- Tie-break.
- The game ends at 2 frozen boards.

### Step 4: Text-mode game and RandomAgent
Add `ai/base.py`, containing the `Agent` interface and a `RandomAgent`. Add `cli.py`, which prints the 3 boards as text and lets a human play any seats against random agents.

**Done when:** 1000 random-vs-random games finish without errors and always end via frozen boards, the limit, or passes.

### Step 5: AI 1, Greedy Best-First Search
`ai/greedy.py`: f(n) = h(n), one step deep, over every legal action on both boards. The heuristic, scored per action:

| Event | Points |
|---|---|
| Capture | +5 |
| Ends on an enemy starting line | +3 |
| Moves 1 row forward | +1 |
| Lands where an enemy can capture it next turn | −5 |

Break ties randomly (seeded). Also place towers during setup with a simple rule: strong towers spread across both boards.

**Done when:** Greedy beats RandomAgent in more than 80% of 200 games (seats rotated).

### Step 6: AI 2, Max^n with Paranoid alpha-beta
`ai/maxn.py`:
- **Max^n:** depth-limited search (default 3 plies = one full round) returning utility vectors `[U1, U2, U3]`. Each player maximises its own component.
- **Paranoid variant:** the other two players minimise the root player's utility, with alpha-beta pruning.
- Evaluation at the cutoff: current score plus the greedy positional terms.
- Move ordering: captures first.
- Iterative deepening within `time_limit`.
- Count nodes expanded, for the metrics.

**Done when:** both modes beat Greedy over 100 games and respect the time limit.

### Step 7: AI 3, MCTS with UCB1
`ai/mcts.py`:
- Selection with UCB1 = t_i/n_i + C·sqrt(ln N / n_i), with C = √2 by default.
- Expand one untried action.
- Rollout: mostly random actions, but a capture is taken 90% of the time when one is available. Stop at the end or after 20 actions, and count the score leader(s) as the winner. (Pure random 60-action rollouts lost to Greedy in testing; this version won 27 of 30.)
- Backpropagate a **reward vector**: 1 for the winner (split on ties), 0 otherwise. Each node scores rewards for the player who moved into it.
- Stop on iteration or time budget. Play the most-visited root action.
- Count rollouts, for the metrics.

**Done when:** it beats Greedy over 100 games at 1 s per move.

### Step 8: Tournament and metrics
`tournament.py`: run N games for any 3 agents, rotating through **all 6 seat orders**. Report per agent:
- win rate
- average score, split into captures and starting-line points
- mean and max time per move
- nodes or rollouts per move

Save the results to CSV and print a table. These are the numbers for slide 10.

### Step 9: Flet UI
`app.py`, styled like the slides (black background, gold, beige boards, white/black/grey towers):
- Start screen: choose the mode (3-AI Free-for-All, or Human vs AI) and pick an agent or "Human" for each seat.
- Show all 3 boards: starting lines in player colours, towers drawn as hexagons, squares and triangles in 3 sizes.
- Setup phase: humans tap a starting square to place the next tower.
- Play: tap a tower to highlight its legal moves and captures, then tap a target.
- Live scores, whose turn it is, and frozen boards greyed out.
- AI turns run in a background thread so the UI never freezes. Add speed control for AI-vs-AI.
- End screen with the winner and final scores.
- Layout must fit a phone screen in portrait (boards stacked) and a laptop (boards side by side).

### Step 10: Run on the phone
1. Test with the Flet app on the phone (`flet run --android`).
2. Build an installable APK with `flet build apk`, including an app name, icon and package id.
3. Write the exact commands in the README.

**Done when:** the APK installs and a full game plays on the phone.

### Step 11: Final polish
- Clean up the README: rules, how to run, screenshots.
- Run a final tournament and put the real numbers into the slides.
- Check that every rule in the spec has a test.
