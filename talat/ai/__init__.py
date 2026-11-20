"""TALAT agents, by name: random (baseline), greedy (AI 1), maxn / paranoid (AI 2), mcts (AI 3)."""
from talat.ai.base import Agent, RandomAgent
from talat.ai.greedy import GreedyAgent
from talat.ai.maxn import MaxnAgent, ParanoidAgent
from talat.ai.mcts import MctsAgent

AGENTS: dict[str, type[Agent]] = {
    "random": RandomAgent,
    "greedy": GreedyAgent,
    "maxn": MaxnAgent,
    "paranoid": ParanoidAgent,
    "mcts": MctsAgent,
}


def make_agent(name: str, seed: int | None = None) -> Agent:
    try:
        return AGENTS[name](seed=seed)
    except KeyError:
        raise ValueError(f"Unknown agent {name!r}; choose from {', '.join(AGENTS)}") from None
