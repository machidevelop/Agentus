"""Global conflict selection.

Two findings conflict when they cannot both be applied: two agents that both
want to change the same job, two that both want to start the same waiting job,
two that both want to delete the same volume. The coordinator has to pick a set
that can actually be executed together.

The obvious way is greedy: sort by value, walk down, drop anything that
collides with something already kept. It is fast and it is wrong often enough
to matter. One large finding that blocks two medium ones wins under greedy even
when the two together are worth more:

    A ($900) conflicts with B ($600) and C ($550), and B and C do not conflict.
    greedy keeps A         -> $900
    the best set is {B, C} -> $1,150

This module picks the maximum-weight set of mutually compatible findings
instead. That is maximum-weight independent set, which is NP-hard in general
and entirely tractable here, because the conflict graph is almost always a
scatter of small components: findings only conflict when they touch the same
resource. So each component is solved on its own, exactly when it is small
enough to enumerate and by a good heuristic when it is not.

Every dropped finding keeps a human-readable reason naming what displaced it,
because a recommendation that vanishes without explanation is worse than one
that was never made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Components up to this size are solved exactly. 24 nodes is at most ~16.7M
# subsets in the worst case, but branch and bound with a greedy incumbent
# prunes almost all of it, and real components are far smaller.
EXACT_COMPONENT_LIMIT = 24


@dataclass
class SelectionResult:
    """Which findings survived, and why the others did not."""

    selected: set[str] = field(default_factory=set)
    dropped: set[str] = field(default_factory=set)
    # dropped id -> the selected ids that displaced it
    displaced_by: dict[str, list[str]] = field(default_factory=dict)
    selected_value: float = 0.0
    dropped_value: float = 0.0
    # Value the greedy rule would have produced, for comparison.
    greedy_value: float = 0.0
    components_solved_exactly: int = 0
    components_solved_heuristically: int = 0
    largest_component: int = 0

    @property
    def improvement_over_greedy(self) -> float:
        return self.selected_value - self.greedy_value


def select_compatible(
    weights: dict[str, float],
    conflicts: set[tuple[str, str]],
) -> SelectionResult:
    """Pick the highest-value set of findings with no conflict between them.

    `weights` maps finding id to its expected value. `conflicts` holds
    unordered pairs that cannot both be applied. Findings with no conflicts are
    always selected, which is the overwhelming majority of them.
    """
    result = SelectionResult()
    if not weights:
        return result

    adjacency: dict[str, set[str]] = {fid: set() for fid in weights}
    for a, b in conflicts:
        if a == b or a not in adjacency or b not in adjacency:
            continue
        adjacency[a].add(b)
        adjacency[b].add(a)

    for component in _components(adjacency):
        result.largest_component = max(result.largest_component, len(component))

        if len(component) == 1:
            only = component[0]
            result.selected.add(only)
            result.selected_value += weights[only]
            result.greedy_value += weights[only]
            continue

        greedy_pick = _greedy(component, adjacency, weights)
        result.greedy_value += sum(weights[f] for f in greedy_pick)

        if len(component) <= EXACT_COMPONENT_LIMIT:
            chosen = _exact(component, adjacency, weights, greedy_pick)
            result.components_solved_exactly += 1
        else:
            chosen = _local_improve(component, adjacency, weights, greedy_pick)
            result.components_solved_heuristically += 1

        result.selected.update(chosen)
        result.selected_value += sum(weights[f] for f in chosen)
        for fid in component:
            if fid in chosen:
                continue
            result.dropped.add(fid)
            result.dropped_value += weights[fid]
            # Name only the neighbours that actually survived: those are the
            # findings a reader can point at as the reason this one went.
            result.displaced_by[fid] = sorted(
                (n for n in adjacency[fid] if n in chosen),
                key=lambda n: weights.get(n, 0.0),
                reverse=True,
            )

    return result


# ------------------------------------------------------------------ internals


def _components(adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Connected components, so each cluster of conflicts is solved alone."""
    seen: set[str] = set()
    out: list[list[str]] = []
    for start in adjacency:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component: list[str] = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        out.append(component)
    return out


def _greedy(
    component: list[str],
    adjacency: dict[str, set[str]],
    weights: dict[str, float],
) -> set[str]:
    """The rule this module replaces, kept to measure against and to seed."""
    chosen: set[str] = set()
    blocked: set[str] = set()
    for fid in sorted(component, key=lambda f: weights.get(f, 0.0), reverse=True):
        if fid in blocked:
            continue
        chosen.add(fid)
        blocked |= adjacency[fid]
    return chosen


def _exact(
    component: list[str],
    adjacency: dict[str, set[str]],
    weights: dict[str, float],
    incumbent: set[str],
) -> set[str]:
    """Exact maximum-weight independent set by branch and bound.

    Ordering by descending weight makes the greedy incumbent strong, so the
    optimistic bound prunes most branches immediately.
    """
    nodes = sorted(component, key=lambda f: weights.get(f, 0.0), reverse=True)
    index = {fid: i for i, fid in enumerate(nodes)}
    n = len(nodes)

    # Neighbour bitmasks, so conflict tests are one AND.
    masks = [0] * n
    for fid in nodes:
        i = index[fid]
        for neighbour in adjacency[fid]:
            if neighbour in index:
                masks[i] |= 1 << index[neighbour]

    values = [weights.get(fid, 0.0) for fid in nodes]
    # suffix[i] is the most any of nodes[i:] could add, ignoring conflicts.
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + max(values[i], 0.0)

    best_value = sum(weights.get(f, 0.0) for f in incumbent)
    best_set = set(incumbent)

    def recurse(i: int, banned: int, current: int, value: float) -> None:
        nonlocal best_value, best_set
        if value + suffix[i] <= best_value + 1e-9:
            return
        if i == n:
            if value > best_value + 1e-9:
                best_value = value
                best_set = {nodes[j] for j in range(n) if current >> j & 1}
            return
        # Take nodes[i] when nothing already chosen conflicts with it.
        if not banned >> i & 1:
            recurse(i + 1, banned | masks[i], current | (1 << i), value + values[i])
        # Or skip it.
        recurse(i + 1, banned, current, value)

    recurse(0, 0, 0, 0.0)
    return best_set


def _local_improve(
    component: list[str],
    adjacency: dict[str, set[str]],
    weights: dict[str, float],
    seed: set[str],
) -> set[str]:
    """Improve a greedy set by (1, 2)-swaps until nothing gets better.

    Drop one selected finding and add two of its neighbours that do not
    conflict with each other or with anything else still selected. This is the
    exact case greedy gets wrong, and it is cheap to check.
    """
    chosen = set(seed)
    improved = True
    while improved:
        improved = False
        for victim in sorted(chosen, key=lambda f: weights.get(f, 0.0)):
            freed = [
                n
                for n in adjacency[victim]
                if n not in chosen and not (adjacency[n] & (chosen - {victim}))
            ]
            if len(freed) < 2:
                continue
            freed.sort(key=lambda f: weights.get(f, 0.0), reverse=True)
            best_pair = None
            best_gain = 0.0
            for i, a in enumerate(freed):
                for b in freed[i + 1 :]:
                    if b in adjacency[a]:
                        continue
                    gain = weights[a] + weights[b] - weights[victim]
                    if gain > best_gain + 1e-9:
                        best_gain = gain
                        best_pair = (a, b)
            if best_pair is not None:
                chosen.discard(victim)
                chosen.update(best_pair)
                improved = True
                break
    return chosen
