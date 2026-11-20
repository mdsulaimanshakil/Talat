from talat.engine import BOARD_PLAYERS, PLAYERS, Board, GameState, Shape, Size, Tower


def t(code: str) -> Tower:
    """'1LH' -> Tower(1, L, H)."""
    return Tower(int(code[0]), Size[code[1]], Shape[code[2]])


def make_state(towers: dict[str, dict[tuple[int, int], str]], to_move: int = 1,
               live_others: bool = True) -> GameState:
    """A play-phase state with the given towers, e.g. {"A": {(1, 2): "1LH"}}.

    With `live_others`, every board not mentioned gets one far-apart pair that can
    still meet (top M-H in the top-right corner, bottom S-T in the bottom-right),
    so it isn't frozen and the game isn't over just because a test is small.
    """
    boards = {name: Board.empty(name) for name in BOARD_PLAYERS}
    for name, squares in towers.items():
        for sq, code in squares.items():
            boards[name][sq] = t(code)
    if live_others:
        for name, (top, bottom) in BOARD_PLAYERS.items():
            if name not in towers:
                boards[name][(0, 4)] = Tower(top, Size.M, Shape.H)
                boards[name][(4, 4)] = Tower(bottom, Size.S, Shape.T)
    return GameState(boards=boards, phase="play", to_move=to_move,
                     hands={p: () for p in PLAYERS}, captured={p: () for p in PLAYERS})
