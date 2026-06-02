# evals/run_evals.py
#
# Evals answer the question: "Is my agent actually working?"
# Not "does it run without crashing" — but "is the output GOOD?"
#
# This is what separates a demo from a system you can trust.
# Run this after making changes to prompts, tools, or the loop.
#
# Usage:
#   python evals/run_evals.py              # Run all 5 niches
#   python evals/run_evals.py --smoke      # Run 1 niche (fast check)

import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import from agent/
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.loop import run_agent
from models.schemas import ResearchBrief


# These are the 5 test niches you run after every change.
# They cover different content types to stress-test the agent.
TEST_NICHES = [
    "morning routines for entrepreneurs",       # Highly competitive niche
    "stoic philosophy for modern life",          # Niche with depth
    "beginner investing mistakes",               # Financial niche, high intent
    "ADHD productivity tips",                    # Health/self-help crossover
    "solo travel safety tips",                   # Niche with clear audience
]

SMOKE_TEST_NICHE = TEST_NICHES[0]  # Quick single-niche test


def score_brief(brief: ResearchBrief, niche: str) -> dict:
    """
    Score a research brief on 5 criteria.
    Each criterion is 0-2 points. Max score: 10.

    These are NOT arbitrary — each one checks something that matters
    for whether the brief is actually usable by a content creator.
    """
    scores = {}

    # 1. Completeness — did the agent fill all required fields?
    completeness = 0
    if len(brief.content_gaps) >= 3:
        completeness += 1
    if len(brief.video_ideas) >= 3:
        completeness += 1
    scores["completeness"] = completeness

    # 2. Specificity — are video titles concrete, not generic?
    specificity = 0
    generic_words = {"tips", "guide", "how to", "everything you need"}
    for idea in brief.video_ideas:
        title_lower = idea.title.lower()
        # A specific title has numbers, names, or concrete problems
        has_number = any(char.isdigit() for char in idea.title)
        has_generic = any(word in title_lower for word in generic_words)
        if has_number and not has_generic:
            specificity += 1
            break
    if brief.tone_profile.common_hooks:
        specificity += 1
    scores["specificity"] = min(specificity, 2)

    # 3. Opportunity score validity — is it reasoned, not just a number?
    opportunity = 0
    if 1 <= brief.opportunity_score <= 10:
        opportunity += 1
    if len(brief.opportunity_score_reasoning) > 50:  # Reasoning must be substantial
        opportunity += 1
    scores["opportunity_score_quality"] = opportunity

    # 4. Actionability — can a creator start making videos immediately?
    actionability = 0
    if brief.recommended_video_length:
        actionability += 1
    if all(idea.hook for idea in brief.video_ideas):  # Every idea has a hook
        actionability += 1
    scores["actionability"] = actionability

    # 5. Niche relevance — is the content actually about the niche searched?
    relevance = 0
    niche_words = set(niche.lower().split())
    themes_text = " ".join(brief.key_themes).lower()
    matching_words = sum(1 for word in niche_words if word in themes_text)
    if matching_words >= 1:
        relevance += 1
    if brief.niche.lower() in niche.lower() or niche.lower() in brief.niche.lower():
        relevance += 1
    scores["niche_relevance"] = relevance

    total = sum(scores.values())
    return {
        "total": total,
        "max": 10,
        "breakdown": scores,
        "grade": "PASS" if total >= 6 else "FAIL"
    }


def run_eval_suite(niches: list[str]) -> dict:
    """Run the full eval suite and return a summary report."""
    results = []
    passed = 0
    failed = 0

    print(f"\n{'='*60}")
    print(f"EVAL SUITE — {len(niches)} niches")
    print(f"{'='*60}")

    for i, niche in enumerate(niches, 1):
        print(f"\n[{i}/{len(niches)}] Testing niche: '{niche}'")

        try:
            brief = run_agent(niche)
            score = score_brief(brief, niche)

            result = {
                "niche": niche,
                "status": "completed",
                "score": score,
                "opportunity_score": brief.opportunity_score,
                "gaps_found": len(brief.content_gaps),
                "ideas_generated": len(brief.video_ideas),
            }

            if score["grade"] == "PASS":
                passed += 1
                print(f"  ✓ PASS — {score['total']}/10 points")
            else:
                failed += 1
                print(f"  ✗ FAIL — {score['total']}/10 points")
                print(f"  Breakdown: {score['breakdown']}")

        except Exception as e:
            failed += 1
            result = {
                "niche": niche,
                "status": "error",
                "error": str(e),
                "score": {"total": 0, "grade": "FAIL"}
            }
            print(f"  ✗ ERROR: {e}")

        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print(f"EVAL RESULTS: {passed}/{len(niches)} passed")
    print(f"Pass rate: {passed/len(niches)*100:.0f}%")
    print(f"{'='*60}\n")

    # Save results to disk
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_niches": len(niches),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed/len(niches)*100:.0f}%",
        "results": results
    }

    results_dir = Path("evals/results")
    results_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = results_dir / f"eval_report_{timestamp}.json"

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Full report saved to: {report_path}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Run eval suite for YouTube Research Agent")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run smoke test (1 niche only, fast check)"
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY") or not os.getenv("YOUTUBE_API_KEY"):
        print("Error: Set ANTHROPIC_API_KEY and YOUTUBE_API_KEY environment variables")
        sys.exit(1)

    niches = [SMOKE_TEST_NICHE] if args.smoke else TEST_NICHES
    report = run_eval_suite(niches)

    # Exit with error code if more than half failed
    # This makes evals usable in CI pipelines
    if report["failed"] > report["total_niches"] / 2:
        sys.exit(1)


if __name__ == "__main__":
    main()
