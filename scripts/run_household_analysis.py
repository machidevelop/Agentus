"""Run the consumer fleet over a household and print the ranked actions.

    python scripts/run_household_analysis.py                  # synthetic household
    python scripts/run_household_analysis.py path/to/export.json
    python scripts/run_household_analysis.py --json            # machine-readable

Read-only. Nothing is filed, cancelled, or submitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from natilah.api.routes.household import analyze_household  # noqa: E402
from natilah.ingestion.household import generate_household, load_household_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", nargs="?", help="Household JSON export. Omit for a demo.")
    parser.add_argument("--seed", type=int, default=7, help="Synthetic household seed.")
    parser.add_argument("--days", type=int, default=120, help="Synthetic window length.")
    parser.add_argument("--top", type=int, default=15, help="How many actions to print.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    args = parser.parse_args()

    if args.export:
        dataset = load_household_json(args.export)
        source = args.export
    else:
        dataset = generate_household(days=args.days, seed=args.seed)
        source = f"synthetic household (seed {args.seed}, {args.days} days)"

    result = analyze_household(dataset, top_n=args.top)

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return 0

    t = result.totals
    print()
    print(f"  Household analysis - {source}")
    print(f"  {len(dataset.claims)} claim lines, {len(dataset.charges)} recurring charges")
    print()
    print(f"  Recoverable now (one-time)   ${t.one_time_recoverable:>12,.2f}")
    print(f"  Recurring savings            ${t.recurring_monthly:>12,.2f} /month")
    print(f"                               ${t.recurring_annual:>12,.2f} /year")
    print()
    print(
        f"  Claimed before deduplication ${t.claimed_one_time:,.2f} one-time, "
        f"${t.claimed_recurring_monthly:,.2f}/month"
    )
    print(
        f"  {result.findings_ranked} actions kept, {result.findings_suppressed} suppressed, "
        f"{result.conflicts_resolved} conflicts resolved"
    )
    if result.selection_gain_monthly_value:
        print(
            f"  Global selection kept ${result.selection_gain_monthly_value:,.2f}/mo that a "
            "greedy rule would have dropped"
        )
    print()

    for action in result.actions:
        money = (
            f"${action.one_time_value:,.2f} once"
            if action.one_time_value
            else f"${action.monthly_value:,.2f}/mo"
        )
        print(f"  #{action.rank:<3} {money:>18}   conf {action.confidence:.2f}   [{action.agent}]")
        print(f"       {action.recommended_action}")
        if action.deadline_note:
            print(f"       [!] {action.deadline_note}")
        if action.alternatives_rejected:
            first = action.alternatives_rejected[0]
            print(
                f"       rejected {len(action.alternatives_rejected)} alternative(s), e.g. "
                f"{first['reason'][:96]}"
            )
        print()

    print("  Nothing above has been filed or cancelled. Every action needs your approval.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
