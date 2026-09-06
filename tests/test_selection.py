"""Global conflict selection: keep the best applicable set, not the first one."""

from __future__ import annotations

import random

from natilah.engine.selection import (
    EXACT_COMPONENT_LIMIT,
    select_compatible,
)


def _brute_force(weights: dict[str, float], conflicts: set[tuple[str, str]]) -> float:
    """Reference answer by enumeration. Only used on tiny cases."""
    ids = sorted(weights)
    best = 0.0
    for mask in range(1 << len(ids)):
        chosen = {ids[i] for i in range(len(ids)) if mask >> i & 1}
        if any(a in chosen and b in chosen for a, b in conflicts):
            continue
        best = max(best, sum(weights[c] for c in chosen))
    return best


def test_two_medium_findings_beat_one_large_blocker():
    """The exact case the old greedy rule got wrong."""
    weights = {"A": 900.0, "B": 600.0, "C": 550.0}
    conflicts = {("A", "B"), ("A", "C")}

    result = select_compatible(weights, conflicts)

    assert result.selected == {"B", "C"}
    assert result.selected_value == 1150.0
    assert result.greedy_value == 900.0
    assert result.improvement_over_greedy == 250.0


def test_dropped_findings_name_what_displaced_them():
    weights = {"A": 900.0, "B": 600.0, "C": 550.0}
    result = select_compatible(weights, {("A", "B"), ("A", "C")})

    assert result.dropped == {"A"}
    assert sorted(result.displaced_by["A"]) == ["B", "C"]


def test_findings_with_no_conflicts_are_all_kept():
    weights = {f"f{i}": float(i + 1) for i in range(50)}
    result = select_compatible(weights, set())

    assert result.selected == set(weights)
    assert not result.dropped
    assert result.selected_value == sum(weights.values())
    assert result.improvement_over_greedy == 0.0


def test_greedy_is_already_optimal_when_the_blocker_wins():
    weights = {"A": 900.0, "B": 300.0, "C": 250.0}
    result = select_compatible(weights, {("A", "B"), ("A", "C")})

    assert result.selected == {"A"}
    assert result.improvement_over_greedy == 0.0


def test_mutually_conflicting_findings_keep_exactly_one():
    weights = {"A": 10.0, "B": 20.0, "C": 30.0}
    conflicts = {("A", "B"), ("B", "C"), ("A", "C")}
    result = select_compatible(weights, conflicts)

    assert result.selected == {"C"}
    assert result.dropped == {"A", "B"}


def test_selection_never_returns_a_conflicting_pair():
    rng = random.Random(19)
    for _ in range(60):
        n = rng.randint(2, 12)
        weights = {f"f{i}": rng.uniform(1.0, 500.0) for i in range(n)}
        ids = sorted(weights)
        conflicts = {
            (a, b)
            for i, a in enumerate(ids)
            for b in ids[i + 1 :]
            if rng.random() < 0.35
        }
        result = select_compatible(weights, conflicts)
        for a, b in conflicts:
            assert not (a in result.selected and b in result.selected)


def test_selection_matches_brute_force_on_small_graphs():
    rng = random.Random(23)
    for _ in range(40):
        n = rng.randint(2, 10)
        weights = {f"f{i}": round(rng.uniform(1.0, 100.0), 2) for i in range(n)}
        ids = sorted(weights)
        conflicts = {
            (a, b)
            for i, a in enumerate(ids)
            for b in ids[i + 1 :]
            if rng.random() < 0.4
        }
        result = select_compatible(weights, conflicts)
        assert result.selected_value == round(_brute_force(weights, conflicts), 10) or abs(
            result.selected_value - _brute_force(weights, conflicts)
        ) < 1e-6


def test_selection_is_never_worse_than_greedy():
    rng = random.Random(31)
    for _ in range(50):
        n = rng.randint(2, 16)
        weights = {f"f{i}": rng.uniform(1.0, 900.0) for i in range(n)}
        ids = sorted(weights)
        conflicts = {
            (a, b)
            for i, a in enumerate(ids)
            for b in ids[i + 1 :]
            if rng.random() < 0.3
        }
        result = select_compatible(weights, conflicts)
        assert result.selected_value >= result.greedy_value - 1e-9


def test_large_components_fall_back_to_the_heuristic_and_still_hold():
    """Past the exact limit the answer is heuristic but must stay valid."""
    n = EXACT_COMPONENT_LIMIT + 12
    weights = {f"f{i}": float(n - i) for i in range(n)}
    # A path, which keeps the whole thing one connected component.
    conflicts = {(f"f{i}", f"f{i + 1}") for i in range(n - 1)}

    result = select_compatible(weights, conflicts)

    assert result.components_solved_heuristically == 1
    assert result.largest_component == n
    for a, b in conflicts:
        assert not (a in result.selected and b in result.selected)
    assert result.selected_value >= result.greedy_value - 1e-9


def test_independent_components_are_solved_separately():
    weights = {"A": 9.0, "B": 6.0, "C": 5.5, "X": 9.0, "Y": 6.0, "Z": 5.5}
    conflicts = {("A", "B"), ("A", "C"), ("X", "Y"), ("X", "Z")}

    result = select_compatible(weights, conflicts)

    assert result.selected == {"B", "C", "Y", "Z"}
    assert result.components_solved_exactly == 2


def test_empty_input_is_handled():
    result = select_compatible({}, set())
    assert result.selected == set()
    assert result.selected_value == 0.0
