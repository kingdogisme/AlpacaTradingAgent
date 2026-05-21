from __future__ import annotations

import argparse
import sys

from tradingagents.alpha_discovery import AlphaDiscoveryService
from tradingagents.alpha_discovery.reporting import compact_candidate, compact_event, count_values, jsonl_event
from tradingagents.default_config import DEFAULT_CONFIG


def main() -> int:
    parser = argparse.ArgumentParser(description="Alpha Discovery cron runner with compact JSONL output.")
    parser.add_argument("job", choices=["discover", "confirm", "run", "health", "errors", "report", "eval"])
    parser.add_argument("--source", default="wsb,dd")
    parser.add_argument("--tier", default="A")
    parser.add_argument("--confirm-tier", default="B,C")
    parser.add_argument("--max-candidates", type=int, default=25)
    parser.add_argument("--max-symbols", type=int, default=6)
    args = parser.parse_args()

    service = AlphaDiscoveryService(config=DEFAULT_CONFIG)
    try:
        payload = _run_job(service, args)
        print(jsonl_event(args.job, payload), flush=True)
        return 0
    except Exception as exc:
        print(
            jsonl_event(
                "job_failed",
                {
                    "job": args.job,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1


def _run_job(service: AlphaDiscoveryService, args: argparse.Namespace):
    if args.job == "discover":
        summary = service.discover(
            sources=[part.strip().lower() for part in args.source.split(",") if part.strip()],
            max_candidates=args.max_candidates,
        )
        return {
            "batch_id": summary["batch_id"],
            "raw_discoveries": summary["raw_discoveries"],
            "tier_counts": summary["tier_counts"],
            "top_rejection_reasons": summary["top_rejection_reasons"],
            "top_candidates": [
                {
                    "ticker": candidate.ticker,
                    "tier": candidate.tier,
                    "alpha_score": candidate.alpha_score,
                    "promotion_gate": (candidate.score_components or {}).get("promotion_gate"),
                    "confirmation_sources": (candidate.score_components or {}).get("confirmation_sources", []),
                    "risk_flags": candidate.risk_flags,
                }
                for candidate in summary.get("candidates", [])[:10]
            ],
        }

    if args.job == "confirm":
        return service.promote_existing(
            tiers=[part.strip() for part in args.confirm_tier.split(",") if part.strip()],
            max_candidates=args.max_candidates,
        )

    if args.job == "run":
        results = service.run_candidates(tier=args.tier, max_symbols=args.max_symbols, execute=False)
        return {
            "tier": args.tier,
            "execute": False,
            "result_count": len(results),
            "run_status_counts": count_values(results, "run_status"),
            "candidates": [compact_candidate(row) for row in results],
        }

    if args.job == "health":
        return service.health_report()

    if args.job == "errors":
        return [compact_event(row) for row in service.list_events(status="error", limit=50)]

    if args.job == "report":
        return service.basket_report(status="open")

    if args.job == "eval":
        return service.evaluation_report(status="open")

    raise ValueError(f"Unsupported AD cron job: {args.job}")


if __name__ == "__main__":
    raise SystemExit(main())
