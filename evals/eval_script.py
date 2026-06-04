# evals/eval_script.py
#
# Evaluates the quality of VideoScript output.
#
# The key question: is this script actually filmable?
# Not "does it parse" — does a creator pick this up and know what to do?
#
# Usage:
#   python evals/eval_script.py --script output/script_xyz.json
#   python evals/eval_script.py --brief output/brief_xyz.json   (generates + scores)

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schemas import VideoScript, ResearchBrief


# ── SCORING RUBRIC ────────────────────────────────────────────────────────────
# 5 criteria, 2 points each. Max: 10. Pass threshold: 6.
#
# These are not arbitrary — each one catches a specific failure mode.
# ─────────────────────────────────────────────────────────────────────────────

BANNED_OPENINGS = [
    "in this video",
    "hey guys",
    "welcome back",
    "today we",
    "today i",
    "today we're",
    "in today's video",
    "hi everyone",
    "what's up",
    "hello everyone",
]


def score_hook_quality(script: VideoScript) -> tuple[int, str]:
    """
    Score 1: Does the hook avoid generic YouTube openings?
    
    The most common failure mode: model writes "In this video I'm going to 
    show you..." despite being told not to. We catch this explicitly.
    """
    hook_lower = script.hook_statement.lower()

    for banned in BANNED_OPENINGS:
        if hook_lower.startswith(banned):
            return 0, f"FAIL: Hook starts with banned phrase '{banned}'"

    # Check for a number, specific claim, or scene-setting language
    has_number = any(char.isdigit() for char in script.hook_statement)
    has_scene_words = any(w in hook_lower for w in ["you", "your", "imagine", "picture", "it's", "right now"])
    has_challenge = any(w in hook_lower for w in ["wrong", "mistake", "backwards", "actually", "truth", "secret"])

    if has_number or has_scene_words or has_challenge:
        return 2, f"PASS: Strong hook — specific and pattern-interrupting"
    else:
        return 1, f"PARTIAL: Hook avoids banned phrases but lacks specificity"


def score_title_specificity(script: VideoScript) -> tuple[int, str]:
    """
    Score 2: Does the primary title contain a number, timeframe, or concrete claim?
    
    Generic titles get no clicks. This enforces specificity.
    """
    title = script.seo.title
    has_number = any(char.isdigit() for char in title)
    has_challenge = any(w in title.lower() for w in ["why", "stop", "wrong", "mistake", "truth", "actually"])
    has_timeframe = any(w in title.lower() for w in ["days", "weeks", "months", "years", "minutes", "hours"])

    specificity_count = sum([has_number, has_challenge, has_timeframe])

    if specificity_count >= 2:
        return 2, f"PASS: Title is specific — has {specificity_count} specificity signals"
    elif specificity_count == 1:
        return 1, f"PARTIAL: Title has some specificity but could be stronger"
    else:
        return 0, f"FAIL: Title is generic — no numbers, timeframes, or concrete claims. Title: '{title}'"


def score_structure_completeness(script: VideoScript) -> tuple[int, str]:
    """
    Score 3: Does the script cover the required structure?
    
    We need at minimum: hook + problem/agitation + at least 2 main points + CTA.
    A script missing these sections is incomplete.
    """
    section_types = [s.section_type.lower() for s in script.sections]

    has_hook = any("hook" in t for t in section_types)
    has_problem = any(t in ("problem", "agitation", "problem_setup") for t in section_types)
    has_main_content = sum(1 for t in section_types if "main" in t or "point" in t or "tip" in t) >= 2
    has_cta = any("cta" in t or "call" in t for t in section_types)

    missing = []
    if not has_hook: missing.append("hook")
    if not has_problem: missing.append("problem/agitation")
    if not has_main_content: missing.append("at least 2 main content sections")
    if not has_cta: missing.append("CTA")

    if not missing:
        return 2, f"PASS: All required sections present ({len(script.sections)} sections total)"
    elif len(missing) <= 1:
        return 1, f"PARTIAL: Missing section types: {missing}"
    else:
        return 0, f"FAIL: Missing required sections: {missing}"


def score_visual_direction(script: VideoScript) -> tuple[int, str]:
    """
    Score 4: Are visual directions specific enough to execute?
    
    "Show relevant footage" is useless. "Split screen showing creator's 
    face on left, phone screen with 47 notifications on right" is actionable.
    """
    vague_phrases = [
        "relevant footage",
        "related visuals",
        "show visuals",
        "b-roll footage",
        "appropriate visuals",
        "visual content",
    ]

    vague_count = 0
    specific_count = 0

    for section in script.sections:
        direction_lower = section.visual_direction.lower()
        is_vague = any(phrase in direction_lower for phrase in vague_phrases)
        # Specific directions tend to be longer and contain concrete nouns
        is_specific = (
            len(section.visual_direction) > 50 and
            not is_vague
        )
        if is_vague:
            vague_count += 1
        elif is_specific:
            specific_count += 1

    total = len(script.sections)
    specific_ratio = specific_count / total if total > 0 else 0

    if specific_ratio >= 0.7:
        return 2, f"PASS: {specific_count}/{total} sections have specific visual direction"
    elif specific_ratio >= 0.4:
        return 1, f"PARTIAL: Only {specific_count}/{total} sections have specific visual direction"
    else:
        return 0, f"FAIL: Most visual directions are vague ({vague_count} vague, {specific_count} specific)"


def score_length_accuracy(script: VideoScript) -> tuple[int, str]:
    """
    Score 5: Is the estimated duration consistent with the word count?
    
    Natural speaking pace is roughly 130-150 words per minute.
    If the model claims 10 minutes but wrote 400 words, something is wrong.
    """
    WORDS_PER_MINUTE_MIN = 120
    WORDS_PER_MINUTE_MAX = 160

    expected_min_words = script.estimated_duration_minutes * WORDS_PER_MINUTE_MIN
    expected_max_words = script.estimated_duration_minutes * WORDS_PER_MINUTE_MAX

    actual_words = script.word_count

    # Also count actual words in sections as a sanity check
    counted_words = sum(len(s.script.split()) for s in script.sections)

    if expected_min_words <= actual_words <= expected_max_words:
        return 2, f"PASS: {actual_words} words consistent with {script.estimated_duration_minutes}min claim"
    elif abs(actual_words - expected_min_words) / expected_min_words < 0.3:
        return 1, f"PARTIAL: {actual_words} words, claimed {script.estimated_duration_minutes}min (expected {expected_min_words:.0f}-{expected_max_words:.0f} words)"
    else:
        return 0, f"FAIL: {actual_words} words is inconsistent with {script.estimated_duration_minutes}min. Counted in sections: {counted_words} words"


def score_script(script: VideoScript) -> dict:
    """Run all scoring criteria and return a summary."""
    criteria = [
        ("hook_quality",          score_hook_quality(script)),
        ("title_specificity",     score_title_specificity(script)),
        ("structure_completeness",score_structure_completeness(script)),
        ("visual_direction",      score_visual_direction(script)),
        ("length_accuracy",       score_length_accuracy(script)),
    ]

    total = sum(score for _, (score, _) in criteria)
    breakdown = {name: {"score": score, "reason": reason} for name, (score, reason) in criteria}

    return {
        "total": total,
        "max": 10,
        "grade": "PASS" if total >= 6 else "FAIL",
        "breakdown": breakdown,
        "script_title": script.seo.title,
        "niche": script.niche,
    }


def main():
    parser = argparse.ArgumentParser(description="Score a VideoScript output")
    parser.add_argument("--script", type=str, help="Path to VideoScript JSON file")
    parser.add_argument("--brief", type=str, help="Path to ResearchBrief JSON (will generate script then score)")
    args = parser.parse_args()

    if args.script:
        path = Path(args.script)
        if not path.exists():
            print(f"File not found: {args.script}")
            sys.exit(1)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        script = VideoScript(**data)

    elif args.brief:
        from script_agent.loop import run_script_agent
        path = Path(args.brief)
        with open(path, encoding="utf-8") as f:
            brief_data = json.load(f)
        brief = ResearchBrief(**brief_data)
        script = run_script_agent(brief)

    else:
        print("Provide --script <path> or --brief <path>")
        sys.exit(1)

    result = score_script(script)

    print(f"\n{'='*60}")
    print(f"SCRIPT EVAL: {result['grade']} ({result['total']}/{result['max']})")
    print(f"Title: {result['script_title']}")
    print(f"{'='*60}")
    for criterion, details in result["breakdown"].items():
        status = "✓" if details["score"] == 2 else ("~" if details["score"] == 1 else "✗")
        print(f"  {status} {criterion}: {details['score']}/2")
        print(f"    {details['reason']}")
    print(f"{'='*60}\n")

    sys.exit(0 if result["grade"] == "PASS" else 1)


if __name__ == "__main__":
    main()
