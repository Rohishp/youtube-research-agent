# main.py
#
# Entry point for the full pipeline.
#
# Usage:
#   python main.py "morning routines for entrepreneurs"
#           → runs full pipeline (research + script)
#
#   python main.py "morning routines for entrepreneurs" --research-only
#           → runs only the research agent, saves brief
#
#   python main.py "morning routines for entrepreneurs" --brief output/brief_xyz.json
#           → skips research, uses existing brief, runs only script agent
#           → useful when iterating on the script agent without burning API quota

import json
import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Research + Script Writing Pipeline"
    )
    parser.add_argument(
        "niche",
        type=str,
        help='The niche to research. Example: "morning routines for entrepreneurs"'
    )
    parser.add_argument(
        "--research-only",
        action="store_true",
        help="Run only the research agent, skip script writing"
    )
    parser.add_argument(
        "--brief",
        type=str,
        default=None,
        help="Path to existing research brief JSON. Skips research, runs only script agent."
    )
    args = parser.parse_args()

    # Validate environment
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set. Check your .env file.")
        sys.exit(1)
    if not os.getenv("YOUTUBE_API_KEY") and args.brief is None and not args.research_only is False:
        # Only need YouTube API if we're doing research
        pass  # Will fail gracefully inside the research agent if needed

    try:
        # ── MODE 1: Full pipeline (default) ──────────────────────────────────
        if not args.research_only and args.brief is None:
            from orchestrator import run_pipeline
            brief, script = run_pipeline(niche=args.niche)

        # ── MODE 2: Research only ─────────────────────────────────────────────
        elif args.research_only:
            from agent.loop import run_agent
            from datetime import datetime
            import json

            if not os.getenv("YOUTUBE_API_KEY"):
                print("Error: YOUTUBE_API_KEY not set. Required for research agent.")
                sys.exit(1)

            brief = run_agent(args.niche)

            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            safe_niche = args.niche.lower().replace(" ", "_")[:40]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            brief_path = output_dir / f"brief_{safe_niche}_{timestamp}.json"

            with open(brief_path, "w", encoding="utf-8") as f:
                json.dump(brief.model_dump(), f, indent=2, ensure_ascii=False)

            print(f"\nResearch brief saved to: {brief_path}")
            print(f"To generate a script from this brief, run:")
            print(f'  python main.py "{args.niche}" --brief {brief_path}')

        # ── MODE 3: Script only (existing brief) ──────────────────────────────
        elif args.brief is not None:
            from script_agent.loop import run_script_agent
            from models.schemas import ResearchBrief
            from datetime import datetime
            import json

            brief_path = Path(args.brief)
            if not brief_path.exists():
                print(f"Error: Brief file not found: {args.brief}")
                sys.exit(1)

            with open(brief_path, encoding="utf-8") as f:
                brief_data = json.load(f)
            brief = ResearchBrief(**brief_data)

            print(f"Loaded research brief for: {brief.niche}")
            script = run_script_agent(brief)

            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            safe_niche = args.niche.lower().replace(" ", "_")[:40]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            script_path = output_dir / f"script_{safe_niche}_{timestamp}.json"

            with open(script_path, "w", encoding="utf-8") as f:
                json.dump(script.model_dump(), f, indent=2, ensure_ascii=False)

            print(f"\nScript saved to: {script_path}")

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
