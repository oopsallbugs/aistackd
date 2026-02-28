from __future__ import annotations

from ai_stack.integrations.shared import load_shared_skills


def test_load_shared_skills_returns_seeded_copy() -> None:
    first = load_shared_skills()
    second = load_shared_skills()

    assert first is not second
    assert set(first.keys()) == set(second.keys())
