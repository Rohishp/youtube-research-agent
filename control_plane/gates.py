# control_plane/gates.py
#
# Quality gates for the pipeline.
#
# A gate is a decision point that routes execution based on output quality.
# It is NOT the same as error handling (which catches unexpected failures).
# It IS expected business logic: "is this output good enough to proceed?"
#
# Your design:
#   Gate 1 — Niche Gate:   opportunity_score < 5 → STOP
#                           videos < 3 or gaps < 2 → RETRY research
#   Gate 2 — Script Gate:  eval_score < 6 → RETRY with improvement agent
#                           retries exhausted → SAVE with warning
#
# Each gate returns a GateDecision — a structured object that tells the
# orchestrator exactly what to do next and why.
# The orchestrator never makes routing decisions itself — it asks the gates.

from dataclasses import dataclass
from typing import Literal
from models.schemas import ResearchBrief, VideoScript


# ── Gate Decision ─────────────────────────────────────────────────────────────
# The output of every gate call.
# action tells the orchestrator what to do.
# reason tells the human (and the trace log) why.

@dataclass
class GateDecision:
    action: Literal["proceed", "retry", "stop"]
    reason: str
    detail: str = ""        # Additional context for logs and user messages


# ── Gate 1: Niche Gate ────────────────────────────────────────────────────────
# Called after the research agent produces a brief.
# Answers: is this niche worth scripting?

# Thresholds — your design decisions, now encoded as constants
MIN_OPPORTUNITY_SCORE = 5       # Below this: niche has no real gap worth filling
MIN_VIDEOS_ANALYZED = 3         # Below this: not enough data to write from
MIN_CONTENT_GAPS = 2            # Below this: research didn't find real opportunities


def niche_gate(brief: ResearchBrief, attempt: int, max_attempts: int = 2) -> GateDecision:
    """
    Decide whether to proceed to script writing, retry research, or stop.

    Parameters
    ----------
    brief : ResearchBrief
        The research brief to evaluate.
    attempt : int
        Which research attempt this is (1-indexed).
    max_attempts : int
        Maximum research attempts before giving up.

    Returns
    -------
    GateDecision with action "proceed", "retry", or "stop"
    """

    # ── Check 1: Is the niche worth anything? ────────────────────────────────
    # A score below 5 means: saturated market, no gaps, not worth a script.
    # No retry — a different research run won't fix a bad niche.
    if brief.opportunity_score < MIN_OPPORTUNITY_SCORE:
        return GateDecision(
            action="stop",
            reason=f"Opportunity score {brief.opportunity_score}/10 is below threshold ({MIN_OPPORTUNITY_SCORE})",
            detail=(
                f"Niche '{brief.niche}' scored {brief.opportunity_score}/10. "
                f"Reasoning: {brief.opportunity_score_reasoning}. "
                f"This niche is too saturated or has insufficient content gaps to justify scripting."
            )
        )

    # ── Check 2: Was the research deep enough? ────────────────────────────────
    # Too few videos or gaps means the brief is thin — retry with a broader query.
    videos_found = len(brief.top_videos_analyzed)
    gaps_found = len(brief.content_gaps)

    research_is_thin = videos_found < MIN_VIDEOS_ANALYZED or gaps_found < MIN_CONTENT_GAPS

    if research_is_thin:
        if attempt >= max_attempts:
            # We've retried enough — proceed with what we have rather than giving up entirely
            # The script will be weaker but a weak script is better than nothing
            return GateDecision(
                action="proceed",
                reason=f"Research thin after {attempt} attempts — proceeding with available data",
                detail=(
                    f"Videos analyzed: {videos_found} (min: {MIN_VIDEOS_ANALYZED}). "
                    f"Content gaps: {gaps_found} (min: {MIN_CONTENT_GAPS}). "
                    f"Max research attempts ({max_attempts}) reached. Script quality may be lower."
                )
            )

        return GateDecision(
            action="retry",
            reason=f"Research too thin (attempt {attempt}/{max_attempts})",
            detail=(
                f"Videos analyzed: {videos_found} (need {MIN_VIDEOS_ANALYZED}+). "
                f"Content gaps: {gaps_found} (need {MIN_CONTENT_GAPS}+). "
                f"Retrying with broader search strategy."
            )
        )

    # ── All checks passed ────────────────────────────────────────────────────
    return GateDecision(
        action="proceed",
        reason=f"Research passed all quality checks",
        detail=(
            f"Score: {brief.opportunity_score}/10 | "
            f"Videos: {videos_found} | "
            f"Gaps: {gaps_found}"
        )
    )


# ── Gate 2: Script Gate ───────────────────────────────────────────────────────
# Called after the script agent produces a script.
# Answers: is this script good enough to save, or does it need improvement?

MIN_SCRIPT_SCORE = 7        # Below this: send to improvement agent
MAX_SCRIPT_RETRIES = 2      # Maximum improvement attempts before saving anyway


def script_gate(eval_score: int, attempt: int, max_attempts: int = MAX_SCRIPT_RETRIES) -> GateDecision:
    """
    Decide whether to save the script, improve it, or save with a warning.

    Parameters
    ----------
    eval_score : int
        Score from eval_script.py (0-10).
    attempt : int
        Which script attempt this is (1-indexed).
    max_attempts : int
        Maximum improvement attempts.

    Returns
    -------
    GateDecision with action "proceed" (save), "retry" (improve), or "stop" (save with warning)
    """

    # ── Script passes quality bar ─────────────────────────────────────────────
    if eval_score >= MIN_SCRIPT_SCORE:
        return GateDecision(
            action="proceed",
            reason=f"Script score {eval_score}/10 meets threshold ({MIN_SCRIPT_SCORE})",
            detail=f"Script passed quality gate on attempt {attempt}."
        )

    # ── Script fails but retries remain ───────────────────────────────────────
    if attempt < max_attempts:
        return GateDecision(
            action="retry",
            reason=f"Script score {eval_score}/10 below threshold ({MIN_SCRIPT_SCORE}) — improving",
            detail=(
                f"Attempt {attempt}/{max_attempts}. "
                f"Sending to improvement agent with specific eval feedback."
            )
        )

    # ── Script fails and retries exhausted ───────────────────────────────────
    # Save it anyway — a low-scoring script is still usable.
    # The warning flag in the output tells the user to review manually.
    return GateDecision(
        action="stop",
        reason=f"Script score {eval_score}/10 after {attempt} attempts — saving with warning",
        detail=(
            f"Max improvement attempts ({max_attempts}) reached. "
            f"Script saved with quality warning. Manual review recommended."
        )
    )
