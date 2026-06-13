# main.py
#
# Entry point for the YouTube Research & Script Pipeline.
#
# Usage:
#   python main.py "morning routines for entrepreneurs"
#   python main.py "stoic philosophy" --research-only
#   python main.py "stoic philosophy" --brief output/brief_xyz.json
#   python main.py --status run_20260611_124102_ba560b
#   python main.py --list

import json
import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="YouTube Research & Script Pipeline")
    parser.add_argument("niche", type=str, nargs="?", default=None,
                        help='Niche to research. Example: "morning routines"')
    parser.add_argument("--research-only", action="store_true",
                        help="Run only the research agent")
    parser.add_argument("--brief", type=str, default=None,
                        help="Path to existing brief JSON. Skips research.")
    parser.add_argument("--status", type=str, default=None,
                        help="Check status of a run by run_id")
    parser.add_argument("--list", action="store_true",
                        help="List recent pipeline runs")
    args = parser.parse_args()

    # ── STATUS CHECK ──────────────────────────────────────────────────────────
    if args.status:
        from control_plane.state import load_state
        try:
            state = load_state(args.status)
            print(json.dumps(state.summary, indent=2))
        except FileNotFoundError:
            print(f"No state found for run: {args.status}")
        return

    # ── LIST RUNS ─────────────────────────────────────────────────────────────
    if args.list:
        from control_plane.state import list_states
        states = list_states(last_n=10)
        if not states:
            print("No pipeline runs found.")
            return
        print(f"\nRecent pipeline runs ({len(states)}):\n")
        for s in states:
            score = f"{s['eval_score']}/10" if s.get('eval_score') else "—"
            cost = f"${s.get('total_cost_usd', 0):.3f}"
            print(f"  {s['run_id']:<35} {s['niche']:<30} {score:<8} {s['status']}")
        print()
        return

    # ── VALIDATE ──────────────────────────────────────────────────────────────
    if not args.niche:
        parser.print_help()
        sys.exit(1)

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set. Check your .env file.")
        sys.exit(1)

    try:
        # ── FULL PIPELINE ─────────────────────────────────────────────────────
        if not args.research_only and args.brief is None:
            from orchestrator import run_pipeline
            state = run_pipeline(niche=args.niche)

        # ── RESEARCH ONLY ─────────────────────────────────────────────────────
        elif args.research_only:
            from agent.loop import run_agent
            from datetime import datetime

            if not os.getenv("YOUTUBE_API_KEY"):
                print("Error: YOUTUBE_API_KEY not set.")
                sys.exit(1)

            brief = run_agent(args.niche)
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            safe_niche = args.niche.lower().replace(" ", "_")[:40]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            brief_path = output_dir / f"brief_{safe_niche}_{timestamp}.json"
            with open(brief_path, "w", encoding="utf-8") as f:
                json.dump(brief.model_dump(), f, indent=2, ensure_ascii=False)
            print(f"\nBrief saved: {brief_path}")
            print(f"To script: python main.py \"{args.niche}\" --brief {brief_path}")

        # ── SCRIPT FROM BRIEF ─────────────────────────────────────────────────
        elif args.brief is not None:
            from orchestrator import run_pipeline
            from models.schemas import ResearchBrief

            brief_path = Path(args.brief)
            if not brief_path.exists():
                print(f"Error: brief not found: {args.brief}")
                sys.exit(1)

            with open(brief_path, encoding="utf-8") as f:
                brief = ResearchBrief(**json.load(f))

            state = run_pipeline(niche=args.niche, research_brief=brief)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except ValueError as e:
        # Gate stopped the pipeline — this is expected behavior, not an error
        print(f"\n{e}")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
