"""Small CLI so the pipeline can be driven without the API.

    python -m deal_rescue.cli shortlist
    python -m deal_rescue.cli rescue meridian
"""

from __future__ import annotations

import argparse
import json
import sys

from deal_rescue.settings import get_settings
from deal_rescue.shortlist import (
    AmbiguousDeal,
    build_shortlist,
    resolve_deal,
    save_shortlist,
    summarize,
)


def _force_utf8_output() -> None:
    """Windows consoles default to cp1252 and the score signals contain '→'
    (e.g. "stage regression: Negotiation → Proposal"). Fix the printer, not the
    data -- that arrow also lands in Salesforce and on the replay."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # non-reconfigurable stream
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(prog="deal-rescue")
    sub = parser.add_subparsers(dest="command", required=True)

    setup_parser = sub.add_parser(
        "setup", help="first-run setup: Salesforce browser login + Tavily key"
    )
    setup_parser.add_argument(
        "--non-interactive", action="store_true",
        help="never prompt; fail if a needed value is missing from .env",
    )

    shortlist_parser = sub.add_parser("shortlist", help="rebuild and print the ranked shortlist")

    rescue_parser = sub.add_parser("rescue", help="run the graph for one deal")
    rescue_parser.add_argument("query", help='account phrase, e.g. "meridian"')
    rescue_parser.add_argument("--json", action="store_true", help="print the full final state")

    whoami_parser = sub.add_parser("whoami", help="show the active user and stored logins")

    eval_parser = sub.add_parser(
        "eval", help="run the synthesis eval suite against the configured backend"
    )
    eval_parser.add_argument(
        "--runs", type=int, default=1, help="repetitions per case (LLM output varies)"
    )
    eval_parser.add_argument("--json", action="store_true", help="print the full report")

    history_parser = sub.add_parser(
        "history", help="recent runs and per-model performance from the run log"
    )
    history_parser.add_argument("--limit", type=int, default=20)
    history_parser.add_argument("--json", action="store_true")

    for with_user in (shortlist_parser, rescue_parser, whoami_parser, eval_parser,
                      history_parser):
        with_user.add_argument(
            "--as", dest="as_user", metavar="EMAIL", default=None,
            help="run as this logged-in user (see `whoami` for the list)",
        )

    args = parser.parse_args(argv)

    if args.command == "setup":
        from deal_rescue.setup_wizard import run_wizard

        return run_wizard(True if args.non_interactive else None)

    from deal_rescue import profiles

    settings = profiles.apply(get_settings(), getattr(args, "as_user", None))

    if args.command == "whoami":
        active = settings.deal_rescue_user
        known = profiles.list_profiles(settings)
        if not known and not active:
            print("No one is logged in yet. Run: python -m deal_rescue.cli setup")
            return 1
        for email in known or ([active] if active else []):
            record = profiles.load(settings, email) or {}
            marker = "*" if email == active else " "
            salesforce = "salesforce" if (record.get("salesforce") or {}).get("refresh_token") else "-"
            google = "google" if (record.get("google") or {}).get("refresh_token") else "-"
            print(f" {marker} {email:36s} {salesforce:10s} {google}")
        print("\n * = active. Switch with --as EMAIL; add a user by running setup as them.")
        return 0

    if args.command == "history":
        from deal_rescue import runlog

        runs = runlog.recent(settings, limit=max(1, args.limit))
        aggregates = runlog.stats(settings)
        if args.json:
            print(json.dumps({"runs": runs, "stats": aggregates}, indent=2, default=str))
        elif not runs:
            print("No runs recorded yet. Run a rescue or an eval first.")
        else:
            print(runlog.format_history(runs, aggregates))
        return 0

    if args.command == "eval":
        from deal_rescue.evals import format_table, run_eval, save_report

        report = run_eval(settings, runs=max(1, args.runs))
        save_report(report, settings)
        print(json.dumps(report, indent=2, default=str) if args.json else format_table(report))
        return 0 if report["summary"]["passed"] == report["summary"]["total"] else 1

    if args.command == "shortlist":
        entries = build_shortlist(settings)
        save_shortlist(entries, settings)
        print(summarize([entry.as_dict() for entry in entries]))
        return 0

    try:
        entry = resolve_deal(args.query, settings)
    except AmbiguousDeal as exc:
        print(f"Ambiguous: {args.query!r}. Candidates:", file=sys.stderr)
        for candidate in exc.candidates:
            print(f"  - {candidate['account_name']} ({candidate['deal_id']})", file=sys.stderr)
        return 2

    from deal_rescue.graph import run_rescue

    state = run_rescue(entry["deal_id"], entry["account_name"], settings)

    if args.json:
        print(json.dumps(state, indent=2, default=str))
        return 0

    print(f"status      : {state.get('status')}")
    print(f"deal        : {entry['account_name']} - {entry['opportunity_name']}")
    if state.get("synthesis"):
        score = state["synthesis"]["deal_score"]
        print(f"score       : {score['value']} (base {score['base_deterministic']}, "
              f"adj {score['llm_adjustment']:+d})")
        print(f"evidence    : {state['synthesis'].get('evidence_level')}")
        print("signals     :")
        for signal in score.get("signals", []):
            print(f"  - {signal}")
    print(f"replay      : {state.get('replay_url')}")
    if state.get("validation_errors"):
        print("validation  :")
        for error in state["validation_errors"]:
            print(f"  ! {error}")
    return 0 if state.get("status") == "published" else 1


if __name__ == "__main__":
    raise SystemExit(main())
