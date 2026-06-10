# orchestrator.py
#
# The governed pipeline.
#
# OLD orchestrator (what you had):
#   brief = research_agent(niche)
#   script = script_agent(brief)
#   save(brief, script)
#
# NEW orchestrator (what this is):
#   brief = research_agent(niche)
#   gate_decision = niche_gate(brief)        ← GATE 1
#   if retry: brief = research_agent(niche)  ← retry with new strategy
#   if stop: tell user why, exit
#
#   script = script_agent(brief)
#   eval_score = score_script(script)
#   gate_decision = script_gate(eval_score)  ← GATE 2
#   if retry: script = improvement_agent(script, feedback)
#   save(brief, script, quality_report)
#
# The orchestrator's job is routing, not deciding.
# It asks the gates what to do. It never makes quality decisions itself.
# This separation means you can change gate thresholds without touching
# the orchestrator, and change the orchestrator flow without touching gates.

import json
import sys
import time
from pathlib import Path
from datetime import datetime

from agent.loop import run_agent as run_research_agent
from script_agent.loop import run_script_agent
from control_plane.gates import niche_gate, script_gate, GateDecision
from improvement_agent.loop import run_improvement_agent, format_eval_feedback
from models.schemas import ResearchBrief, VideoScript


# ── Import the script scorer ──────────────────────────────────────────────────
# We reuse the existing eval logic — no duplication
sys.path.insert(0, str(Path(__file__).parent))
from evals.eval_script import score_script


def _build_retry_niche_prompt(niche: str, attempt: int) -> str:
    """
    Modify the research approach on retry.
    First attempt: exact niche. Second attempt: broader angle.
    This gives the research agent a better chance of finding content.
    """
    if attempt == 1:
        return niche
    elif attempt == 2:
        # Broaden the search — add "tips" or "guide" to find more content
        return f"{niche} tips guide advice"
    else:
        return niche


def run_pipeline(
    niche: str,
    save_outputs: bool = True,
    research_brief: ResearchBrief = None,
) -> tuple[ResearchBrief, VideoScript, dict]:
    """
    Run the governed pipeline with quality gates.

    Returns
    -------
    tuple of (ResearchBrief, VideoScript, quality_report)
    quality_report contains gate decisions and final eval scores.
    """
    pipeline_start = time.time()
    quality_report = {
        "niche": niche,
        "research_attempts": 0,
        "script_attempts": 0,
        "niche_gate_decisions": [],
        "script_gate_decisions": [],
        "final_eval_score": None,
        "warnings": [],
    }

    print(f"\n{'='*60}")
    print(f"GOVERNED PIPELINE: '{niche}'")
    print(f"{'='*60}")

    # ── STAGE 1: RESEARCH WITH NICHE GATE ────────────────────────────────────
    brief = None

    if research_brief is not None:
        print("\n[Pipeline] Stage 1: SKIPPED (using provided brief)")
        brief = research_brief
    else:
        max_research_attempts = 2

        for research_attempt in range(1, max_research_attempts + 1):
            print(f"\n[Pipeline] Stage 1: Research Agent (attempt {research_attempt}/{max_research_attempts})")

            search_niche = _build_retry_niche_prompt(niche, research_attempt)
            if research_attempt > 1:
                print(f"[Pipeline] Retrying with broader query: '{search_niche}'")

            brief = run_research_agent(search_niche)
            quality_report["research_attempts"] = research_attempt

            # ── NICHE GATE ────────────────────────────────────────────────────
            print(f"\n[Gate 1] Evaluating research brief...")
            decision = niche_gate(brief, attempt=research_attempt, max_attempts=max_research_attempts)
            quality_report["niche_gate_decisions"].append({
                "attempt": research_attempt,
                "action": decision.action,
                "reason": decision.reason,
                "detail": decision.detail,
            })

            print(f"[Gate 1] Decision: {decision.action.upper()}")
            print(f"[Gate 1] Reason: {decision.reason}")

            if decision.action == "stop":
                # Niche is not worth scripting — exit cleanly
                print(f"\n[Pipeline] STOPPED by Niche Gate.")
                print(f"[Pipeline] {decision.detail}")
                _save_quality_report(quality_report, niche, save_outputs)
                raise ValueError(
                    f"Pipeline stopped: {decision.reason}\n{decision.detail}"
                )

            elif decision.action == "proceed":
                print(f"[Gate 1] ✓ Research passed. Proceeding to script.")
                break

            elif decision.action == "retry":
                print(f"[Gate 1] Research too thin. Retrying...")
                if research_attempt == max_research_attempts:
                    # Last attempt — gate will have returned "proceed" already
                    # This branch shouldn't be reached but handle it gracefully
                    break
                continue

    # ── STAGE 2: SCRIPT WITH SCRIPT GATE ─────────────────────────────────────
    print(f"\n[Pipeline] Stage 2: Script Writing Agent")
    script = run_script_agent(brief)
    quality_report["script_attempts"] = 1

    max_script_attempts = 2

    for script_attempt in range(1, max_script_attempts + 1):

        if script_attempt > 1:
            # Run improvement agent with specific feedback
            print(f"\n[Pipeline] Stage 2b: Improvement Agent (attempt {script_attempt}/{max_script_attempts})")
            feedback = format_eval_feedback(eval_result)
            script = run_improvement_agent(script, feedback)
            quality_report["script_attempts"] = script_attempt

        # Evaluate the script
        print(f"\n[Gate 2] Evaluating script (attempt {script_attempt})...")
        eval_result = score_script(script)
        eval_score = eval_result["total"]
        quality_report["final_eval_score"] = eval_score

        print(f"[Gate 2] Eval score: {eval_score}/10")
        for criterion, details in eval_result["breakdown"].items():
            status = "✓" if details["score"] == 2 else ("~" if details["score"] == 1 else "✗")
            print(f"[Gate 2]   {status} {criterion}: {details['score']}/2")

        # ── SCRIPT GATE ───────────────────────────────────────────────────────
        decision = script_gate(eval_score, attempt=script_attempt, max_attempts=max_script_attempts)
        quality_report["script_gate_decisions"].append({
            "attempt": script_attempt,
            "eval_score": eval_score,
            "action": decision.action,
            "reason": decision.reason,
        })

        print(f"[Gate 2] Decision: {decision.action.upper()}")
        print(f"[Gate 2] Reason: {decision.reason}")

        if decision.action == "proceed":
            print(f"[Gate 2] ✓ Script passed quality gate.")
            break

        elif decision.action == "stop":
            # Retries exhausted — save with warning
            quality_report["warnings"].append(
                f"Script saved below quality threshold ({eval_score}/10) after {script_attempt} attempts"
            )
            print(f"[Gate 2] ⚠ Saving with quality warning: score {eval_score}/10")
            break

        elif decision.action == "retry":
            print(f"[Gate 2] Script needs improvement. Sending to improvement agent...")
            continue

    # ── SAVE OUTPUTS ─────────────────────────────────────────────────────────
    total_time = time.time() - pipeline_start

    if save_outputs:
        _save_all_outputs(brief, script, quality_report, niche)

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE in {total_time:.1f}s")
    print(f"{'='*60}")
    print(f"Niche:             {brief.niche}")
    print(f"Opportunity:       {brief.opportunity_score}/10")
    print(f"Research attempts: {quality_report['research_attempts']}")
    print(f"Script attempts:   {quality_report['script_attempts']}")
    print(f"Final eval score:  {quality_report['final_eval_score']}/10")
    print(f"Video title:       {script.seo.title}")
    if quality_report["warnings"]:
        for w in quality_report["warnings"]:
            print(f"⚠ WARNING: {w}")
    print(f"{'='*60}\n")

    return brief, script, quality_report


def _save_all_outputs(
    brief: ResearchBrief,
    script: VideoScript,
    quality_report: dict,
    niche: str,
) -> None:
    """Save all pipeline outputs to disk."""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    safe_niche = niche.lower().replace(" ", "_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Research brief
    brief_path = output_dir / f"brief_{safe_niche}_{timestamp}.json"
    with open(brief_path, "w", encoding="utf-8") as f:
        json.dump(brief.model_dump(), f, indent=2, ensure_ascii=False)

    # Video script
    script_path = output_dir / f"script_{safe_niche}_{timestamp}.json"
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script.model_dump(), f, indent=2, ensure_ascii=False)

    # Quality report
    report_path = output_dir / f"quality_{safe_niche}_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)

    # Readable script
    readable_path = output_dir / f"script_readable_{safe_niche}_{timestamp}.txt"
    _save_readable_script(script, readable_path)

    print(f"\n[Pipeline] Outputs saved:")
    print(f"  Brief:          {brief_path}")
    print(f"  Script:         {script_path}")
    print(f"  Quality report: {report_path}")
    print(f"  Readable:       {readable_path}")


def _save_quality_report(quality_report: dict, niche: str, save: bool) -> None:
    """Save quality report even when pipeline is stopped early."""
    if not save:
        return
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    safe_niche = niche.lower().replace(" ", "_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"quality_{safe_niche}_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(quality_report, f, indent=2, ensure_ascii=False)
    print(f"[Pipeline] Quality report saved: {path}")


def _save_readable_script(script: VideoScript, path: Path) -> None:
    """Save human-readable plain text version of the script."""
    lines = [
        f"VIDEO SCRIPT: {script.seo.title}",
        "=" * 60,
        f"Duration: ~{script.estimated_duration_minutes} minutes ({script.word_count} words)",
        f"Niche: {script.niche}",
        f"Addresses gap: {script.addresses_gap}",
        "",
        "SEO PACKAGE",
        "-" * 40,
        f"Title: {script.seo.title}",
    ]
    for i, v in enumerate(script.seo.title_variants, 1):
        lines.append(f"Variant {i}: {v}")
    lines += [
        f"Thumbnail: {script.seo.thumbnail_concept}",
        f"Thumbnail text: {script.seo.thumbnail_text}",
        f"Tags: {', '.join(script.seo.tags)}",
        "",
        "OPENING LINE",
        "-" * 40,
        f'"{script.hook_statement}"',
        "",
        "FULL SCRIPT",
        "-" * 40,
    ]
    for i, section in enumerate(script.sections, 1):
        lines += [
            f"\n[SECTION {i}: {section.title.upper()}]",
            f"Type: {section.section_type} | Duration: ~{section.duration_seconds}s",
            f"Visual: {section.visual_direction}",
            f"B-Roll: {section.b_roll_notes}",
            "",
            section.script,
        ]
    lines += [
        "",
        "PRODUCTION NOTES",
        "-" * 40,
        script.production_notes,
        "",
        "REWATCH HOOK",
        "-" * 40,
        script.rewatch_hook,
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
