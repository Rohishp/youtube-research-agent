# orchestrator.py
#
# The governed pipeline — now state-centric.
#
# BEFORE (multiple variables):
#   brief = run_research_agent(niche)
#   script = run_script_agent(brief)
#   quality_report = {...}
#   tracer = Tracer(...)
#
# AFTER (one state object):
#   state = PipelineState(niche=niche)
#   state = research_stage(state)
#   save_state(state)
#   state = script_stage(state)
#   save_state(state)
#
# Every stage reads from state and writes back to state.
# State is saved after every stage transition.
# If the process crashes, load_state(run_id) picks up where it stopped.

import json
import sys
import time
from pathlib import Path
from datetime import datetime

from agent.loop import run_agent as run_research_agent
from script_agent.loop import run_script_agent
from control_plane.gates import niche_gate, script_gate
from control_plane.state import PipelineState, save_state, load_state
from improvement_agent.loop import run_improvement_agent, format_eval_feedback
from models.schemas import ResearchBrief, VideoScript

sys.path.insert(0, str(Path(__file__).parent))
from evals.eval_script import score_script


def _build_retry_niche_prompt(niche: str, attempt: int) -> str:
    if attempt == 1:
        return niche
    elif attempt == 2:
        return f"{niche} tips guide advice"
    return niche


def run_pipeline(
    niche: str,
    save_outputs: bool = True,
    research_brief: ResearchBrief = None,
    run_id: str = None,
) -> PipelineState:
    """
    Run the governed pipeline. Returns the unified PipelineState.

    The state object contains everything: brief, script, eval scores,
    gate decisions, cost, timing. One object, one source of truth.
    """
    # ── CREATE STATE ──────────────────────────────────────────────────────────
    sif run_id:
        state = PipelineState(run_id=run_id, niche=niche)
    else:
        state = PipelineState(niche=niche)
    pipeline_start = time.perf_counter()

    print(f"\n{'='*60}")
    print(f"GOVERNED PIPELINE: '{niche}'")
    print(f"Run ID: {state.run_id}")
    print(f"{'='*60}")

    try:
        # ── STAGE 1: RESEARCH ─────────────────────────────────────────────────
        if research_brief is not None:
            print("\n[Pipeline] Stage 1: SKIPPED (using provided brief)")
            state.research_brief = research_brief
            state.status = "research_complete"
            save_state(state)
        else:
            max_research_attempts = 2

            for research_attempt in range(1, max_research_attempts + 1):
                print(f"\n[Pipeline] Stage 1: Research Agent (attempt {research_attempt}/{max_research_attempts})")

                state.status = "researching"
                search_niche = _build_retry_niche_prompt(niche, research_attempt)
                state.research_query_used = search_niche

                if research_attempt > 1:
                    print(f"[Pipeline] Retrying with broader query: '{search_niche}'")

                stage_start = time.perf_counter()
                state.research_brief = run_research_agent(search_niche)
                stage_duration = time.perf_counter() - stage_start

                state.research_attempts = research_attempt

                # Record stage timing
                state.stage_timings.append({
                    "stage": "research",
                    "attempt": research_attempt,
                    "duration_seconds": round(stage_duration, 2),
                })

                # ── NICHE GATE ────────────────────────────────────────────────
                print(f"\n[Gate 1] Evaluating research brief...")
                decision = niche_gate(
                    state.research_brief,
                    attempt=research_attempt,
                    max_attempts=max_research_attempts
                )

                state.record_gate_decision(
                    gate="niche_gate",
                    attempt=research_attempt,
                    action=decision.action,
                    reason=decision.reason,
                    detail=decision.detail,
                )

                print(f"[Gate 1] Decision: {decision.action.upper()}")
                print(f"[Gate 1] Reason: {decision.reason}")

                # Save state after gate decision — crash protection
                save_state(state)

                if decision.action == "stop":
                    state.status = "stopped"
                    state.duration_seconds = time.perf_counter() - pipeline_start
                    save_state(state)
                    print(f"\n[Pipeline] STOPPED by Niche Gate: {decision.detail}")
                    return state

                elif decision.action == "proceed":
                    state.status = "research_complete"
                    save_state(state)
                    print(f"[Gate 1] ✓ Research passed. Proceeding to script.")
                    break

                elif decision.action == "retry":
                    print(f"[Gate 1] Research too thin. Retrying...")
                    if research_attempt == max_research_attempts:
                        state.status = "research_complete"
                        save_state(state)
                        break
                    continue

        # ── STAGE 2: SCRIPT ───────────────────────────────────────────────────
        print(f"\n[Pipeline] Stage 2: Script Writing Agent")
        state.status = "scripting"
        save_state(state)

        stage_start = time.perf_counter()
        state.video_script = run_script_agent(state.research_brief)
        stage_duration = time.perf_counter() - stage_start

        state.script_attempts = 1
        state.stage_timings.append({
            "stage": "script",
            "attempt": 1,
            "duration_seconds": round(stage_duration, 2),
        })

        # ── EVALUATION + SCRIPT GATE ──────────────────────────────────────────
        max_script_attempts = 2

        for script_attempt in range(1, max_script_attempts + 1):

            if script_attempt > 1:
                print(f"\n[Pipeline] Stage 2b: Improvement Agent (attempt {script_attempt}/{max_script_attempts})")
                state.status = "improving"
                save_state(state)

                improve_start = time.perf_counter()
                state.video_script = run_improvement_agent(
                    state.video_script,
                    state.eval_feedback
                )
                improve_duration = time.perf_counter() - improve_start

                state.script_attempts = script_attempt
                state.stage_timings.append({
                    "stage": "improvement",
                    "attempt": script_attempt,
                    "duration_seconds": round(improve_duration, 2),
                })

            state.status = "evaluating"
            print(f"\n[Gate 2] Evaluating script (attempt {script_attempt})...")
            eval_result = score_script(state.video_script)
            state.eval_score = eval_result["total"]
            state.eval_breakdown = eval_result["breakdown"]

            print(f"[Gate 2] Eval score: {state.eval_score}/10")
            for criterion, details in eval_result["breakdown"].items():
                status_icon = "✓" if details["score"] == 2 else ("~" if details["score"] == 1 else "✗")
                print(f"[Gate 2]   {status_icon} {criterion}: {details['score']}/2")

            decision = script_gate(state.eval_score, attempt=script_attempt, max_attempts=max_script_attempts)

            state.record_gate_decision(
                gate="script_gate",
                attempt=script_attempt,
                action=decision.action,
                reason=decision.reason,
                eval_score=state.eval_score,
            )

            save_state(state)

            print(f"[Gate 2] Decision: {decision.action.upper()}")
            print(f"[Gate 2] Reason: {decision.reason}")

            if decision.action == "proceed":
                print(f"[Gate 2] ✓ Script passed quality gate.")
                break

            elif decision.action == "stop":
                warning = f"Script saved below quality threshold ({state.eval_score}/10) after {script_attempt} attempts"
                state.add_warning(warning)
                print(f"[Gate 2] ⚠ {warning}")
                break

            elif decision.action == "retry":
                state.eval_feedback = format_eval_feedback(eval_result)
                print(f"[Gate 2] Script needs improvement. Sending to improvement agent...")
                continue

        # ── COMPLETE ──────────────────────────────────────────────────────────
        state.status = "completed"
        state.duration_seconds = round(time.perf_counter() - pipeline_start, 2)
        save_state(state)

        if save_outputs:
            _save_deliverables(state)

        # ── SUMMARY ───────────────────────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"PIPELINE COMPLETE in {state.duration_seconds}s")
        print(f"{'='*60}")
        print(f"Run ID:            {state.run_id}")
        print(f"Niche:             {state.research_brief.niche}")
        print(f"Opportunity:       {state.research_brief.opportunity_score}/10")
        print(f"Research attempts: {state.research_attempts}")
        print(f"Script attempts:   {state.script_attempts}")
        print(f"Final eval score:  {state.eval_score}/10")
        print(f"Video title:       {state.video_script.seo.title}")
        if state.warnings:
            for w in state.warnings:
                print(f"⚠ WARNING: {w}")
        print(f"State saved:       output/states/{state.run_id}.json")
        print(f"{'='*60}\n")

        return state

    except Exception as e:
        state.set_error(str(e))
        state.duration_seconds = round(time.perf_counter() - pipeline_start, 2)
        save_state(state)
        raise


def _save_deliverables(state: PipelineState) -> None:
    """Save human-readable deliverables alongside the state file."""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    safe_niche = state.niche.lower().replace(" ", "_")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if state.research_brief:
        path = output_dir / f"brief_{safe_niche}_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.research_brief.model_dump(), f, indent=2, ensure_ascii=False)

    if state.video_script:
        path = output_dir / f"script_{safe_niche}_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.video_script.model_dump(), f, indent=2, ensure_ascii=False)

        readable_path = output_dir / f"script_readable_{safe_niche}_{timestamp}.txt"
        _save_readable_script(state.video_script, readable_path)

    print(f"\n[Pipeline] Deliverables saved to output/")


def _save_readable_script(script: VideoScript, path: Path) -> None:
    lines = [
        f"VIDEO SCRIPT: {script.seo.title}",
        "=" * 60,
        f"Duration: ~{script.estimated_duration_minutes} minutes ({script.word_count} words)",
        f"Niche: {script.niche}",
        f"Addresses gap: {script.addresses_gap}",
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
            "",
            section.script,
        ]
    lines += ["", "REWATCH HOOK", "-" * 40, script.rewatch_hook]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
