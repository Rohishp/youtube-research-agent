# orchestrator.py
#
# The orchestrator connects Agent 1 (Research) and Agent 2 (Script Writing).
# This is the entire "multi-agent system" — about 50 lines of Python.
#
# No framework. No magic. Just:
#   1. Run Agent 1, get output
#   2. Pass output as input to Agent 2
#   3. Return both outputs
#
# ── WHY THIS MATTERS ─────────────────────────────────────────────────────────
# This pattern — output of Agent N becomes input to Agent N+1 — is the
# foundation of every production multi-agent pipeline you'll ever build.
#
# LangGraph calls it a "graph with edges."
# CrewAI calls it a "process with task handoffs."
# OpenAI Agents SDK calls it "handoffs."
#
# They all describe the same thing: this file.
# The only difference is they abstract away the explicit JSON passing
# and give you a framework to manage it. Understanding the raw version
# first means you'll never be confused by what a framework is doing.
# ─────────────────────────────────────────────────────────────────────────────

import json
import time
from pathlib import Path
from datetime import datetime
from agent.loop import run_agent as run_research_agent
from script_agent.loop import run_script_agent
from models.schemas import ResearchBrief, VideoScript


def run_pipeline(
    niche: str,
    save_outputs: bool = True,
    research_brief: ResearchBrief = None,   # Optional: skip research, use existing brief
) -> tuple[ResearchBrief, VideoScript]:
    """
    Full pipeline: niche keyword → research brief → video script.

    Parameters
    ----------
    niche : str
        The YouTube niche to research and script for.
    save_outputs : bool
        Whether to save JSON files to disk. Default True.
    research_brief : ResearchBrief, optional
        If provided, skips the research stage and goes straight to scripting.
        Useful when you already have a brief and want to regenerate the script,
        or when iterating on the script agent without burning YouTube API quota.

    Returns
    -------
    tuple[ResearchBrief, VideoScript]
        Both outputs. The brief is useful for downstream agents
        (e.g. a future thumbnail generator that reads the brief's tone_profile).
    """
    pipeline_start = time.time()

    print(f"\n{'='*60}")
    print(f"PIPELINE START: '{niche}'")
    print(f"{'='*60}")

    # ── STAGE 1: RESEARCH ────────────────────────────────────────────────────
    if research_brief is not None:
        # Skip research — use the provided brief
        # This is useful for iterating on the script agent without
        # making YouTube API calls every time
        print("\n[Pipeline] Stage 1: SKIPPED (using provided research brief)")
        brief = research_brief
    else:
        print("\n[Pipeline] Stage 1: Research Agent")
        stage1_start = time.time()
        brief = run_research_agent(niche)
        stage1_time = time.time() - stage1_start
        print(f"\n[Pipeline] Stage 1 complete in {stage1_time:.1f}s")
        print(f"[Pipeline] Opportunity score: {brief.opportunity_score}/10")
        print(f"[Pipeline] Gaps found: {len(brief.content_gaps)}")
        print(f"[Pipeline] Ideas generated: {len(brief.video_ideas)}")

    # ── STAGE 2: SCRIPT WRITING ───────────────────────────────────────────────
    print("\n[Pipeline] Stage 2: Script Writing Agent")
    stage2_start = time.time()
    script = run_script_agent(brief)
    stage2_time = time.time() - stage2_start
    print(f"\n[Pipeline] Stage 2 complete in {stage2_time:.1f}s")

    # ── SAVE OUTPUTS ─────────────────────────────────────────────────────────
    if save_outputs:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        safe_niche = niche.lower().replace(" ", "_")[:40]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save research brief
        brief_path = output_dir / f"brief_{safe_niche}_{timestamp}.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief.model_dump(), f, indent=2, ensure_ascii=False)

        # Save video script
        script_path = output_dir / f"script_{safe_niche}_{timestamp}.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script.model_dump(), f, indent=2, ensure_ascii=False)

        # Save a human-readable version of the script
        readable_path = output_dir / f"script_readable_{safe_niche}_{timestamp}.txt"
        _save_readable_script(script, readable_path)

        print(f"\n[Pipeline] Outputs saved:")
        print(f"  Research brief: {brief_path}")
        print(f"  Script JSON:    {script_path}")
        print(f"  Readable:       {readable_path}")

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE in {total_time:.1f}s")
    print(f"{'='*60}")
    print(f"Niche:           {brief.niche}")
    print(f"Opportunity:     {brief.opportunity_score}/10")
    print(f"Video title:     {script.seo.title}")
    print(f"Script length:   {script.word_count} words / {script.estimated_duration_minutes} min")
    print(f"Sections:        {len(script.sections)}")
    print(f"Addresses gap:   {script.addresses_gap}")
    print(f"{'='*60}\n")

    return brief, script


def _save_readable_script(script: VideoScript, path: Path) -> None:
    """
    Save a human-readable plain text version of the script.
    This is what a creator actually reads when filming.
    JSON is for machines. This is for humans.
    """
    lines = []

    lines.append(f"VIDEO SCRIPT: {script.seo.title}")
    lines.append("=" * 60)
    lines.append(f"Duration: ~{script.estimated_duration_minutes} minutes ({script.word_count} words)")
    lines.append(f"Niche: {script.niche}")
    lines.append(f"Addresses gap: {script.addresses_gap}")
    lines.append("")

    lines.append("SEO PACKAGE")
    lines.append("-" * 40)
    lines.append(f"Title: {script.seo.title}")
    for i, variant in enumerate(script.seo.title_variants, 1):
        lines.append(f"Title variant {i}: {variant}")
    lines.append(f"Thumbnail: {script.seo.thumbnail_concept}")
    lines.append(f"Thumbnail text: {script.seo.thumbnail_text}")
    lines.append(f"Tags: {', '.join(script.seo.tags)}")
    lines.append("")
    lines.append("DESCRIPTION:")
    lines.append(script.seo.description)
    lines.append("")

    lines.append("OPENING LINE")
    lines.append("-" * 40)
    lines.append(f'"{script.hook_statement}"')
    lines.append("")

    lines.append("FULL SCRIPT")
    lines.append("-" * 40)

    for i, section in enumerate(script.sections, 1):
        lines.append(f"\n[SECTION {i}: {section.title.upper()}]")
        lines.append(f"Type: {section.section_type} | Duration: ~{section.duration_seconds}s")
        lines.append(f"Visual: {section.visual_direction}")
        lines.append(f"B-Roll: {section.b_roll_notes}")
        lines.append("")
        lines.append(section.script)

    lines.append("")
    lines.append("PRODUCTION NOTES")
    lines.append("-" * 40)
    lines.append(script.production_notes)
    lines.append("")
    lines.append("PATTERN INTERRUPT MOMENTS")
    lines.append("-" * 40)
    for moment in script.pattern_interrupt_moments:
        lines.append(f"  • {moment}")
    lines.append("")
    lines.append(f"REWATCH HOOK: {script.rewatch_hook}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
