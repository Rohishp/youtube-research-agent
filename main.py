# main.py
#
# Entry point. Run this from the command line:
#   python main.py "morning routines for busy professionals"
#   python main.py "stoic philosophy for modern life"
#   python main.py "beginner investing mistakes"

from dotenv import load_dotenv
load_dotenv()                    # ← reads .env and loads keys into environment

import json
import sys
import os
from datetime import datetime
from pathlib import Path
from agent.loop import run_agent


def main():
    # Get niche from command line argument
    if len(sys.argv) < 2:
        print("Usage: python main.py \"your niche here\"")
        print("Example: python main.py \"morning routines for entrepreneurs\"")
        sys.exit(1)

    niche = sys.argv[1]

    # Validate API keys are set before starting
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Copy .env.example to .env and add your keys")
        sys.exit(1)

    if not os.getenv("YOUTUBE_API_KEY"):
        print("Error: YOUTUBE_API_KEY environment variable not set")
        sys.exit(1)

    # Run the agent
    try:
        brief = run_agent(niche)

        # Save output to disk
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        # Create a filename from the niche and timestamp
        safe_niche = niche.lower().replace(" ", "_")[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = output_dir / f"{safe_niche}_{timestamp}.json"

        # Save the structured brief
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(brief.model_dump(), f, indent=2, ensure_ascii=False)

        # Print summary to terminal
        print(f"\n{'='*60}")
        print(f"RESEARCH BRIEF: {brief.niche.upper()}")
        print(f"{'='*60}")
        print(f"Opportunity Score: {brief.opportunity_score}/10")
        print(f"Reasoning: {brief.opportunity_score_reasoning}")
        print(f"\nKey Themes:")
        for theme in brief.key_themes:
            print(f"  • {theme}")
        print(f"\nContent Gaps Found: {len(brief.content_gaps)}")
        for gap in brief.content_gaps:
            print(f"  • {gap.gap_title} (demand: {gap.estimated_demand})")
        print(f"\nVideo Ideas Generated: {len(brief.video_ideas)}")
        for idea in brief.video_ideas:
            print(f"  • {idea.title}")
        print(f"\nSummary: {brief.summary}")
        print(f"\nFull brief saved to: {filename}")
        print(f"{'='*60}\n")

    except ValueError as e:
        print(f"\nError parsing agent output: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"\nAgent error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
