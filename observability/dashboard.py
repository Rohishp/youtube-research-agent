#!/usr/bin/env python3
# observability/dashboard.py
#
# Reads all trace files and shows performance patterns across runs.
# This answers the three questions you said "I don't know" to:
#
#   Q1: Which run failed and why?
#      → Read any trace file for the full diagnostic
#
#   Q2: Which niche produced the best quality output?
#      → Dashboard shows eval scores ranked by niche
#
#   Q3: What did each run cost?
#      → Dashboard shows cost per run and cumulative cost
#
# Usage:
#   python observability/dashboard.py
#   python observability/dashboard.py --last 5
#   python observability/dashboard.py --niche "morning routines"

import json
import argparse
from pathlib import Path
from datetime import datetime


TRACES_DIR = Path("output/traces")


def load_traces(last_n: int = None, niche_filter: str = None) -> list[dict]:
    """Load trace files from disk, newest first."""
    if not TRACES_DIR.exists():
        return []

    files = sorted(TRACES_DIR.glob("*.json"), reverse=True)

    if last_n:
        files = files[:last_n]

    traces = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fp:
                trace = json.load(fp)
            if niche_filter and niche_filter.lower() not in trace.get("niche", "").lower():
                continue
            traces.append(trace)
        except Exception:
            pass

    return traces


def format_cost(cost: float) -> str:
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.3f}"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{seconds/60:.1f}m"


def show_dashboard(traces: list[dict]) -> None:
    if not traces:
        print("No trace files found in output/traces/")
        print("Run the pipeline at least once to generate traces.")
        return

    print(f"\n{'='*65}")
    print(f"  PIPELINE DASHBOARD  —  {len(traces)} run(s) analysed")
    print(f"{'='*65}")

    # ── SUMMARY STATS ─────────────────────────────────────────────────────────
    completed = [t for t in traces if t.get("status") == "completed"]
    stopped   = [t for t in traces if t.get("status") in ("stopped", "stopped_by_gate")]
    failed    = [t for t in traces if t.get("status") == "failed"]

    total_cost = sum(t.get("total_cost_usd", 0) for t in traces)
    total_tokens = sum(
        t.get("total_tokens_input", 0) + t.get("total_tokens_output", 0)
        for t in traces
    )

    print(f"\n  STATUS")
    print(f"  {'Completed:':<20} {len(completed)}")
    print(f"  {'Stopped by gate:':<20} {len(stopped)}")
    print(f"  {'Failed:':<20} {len(failed)}")

    if completed:
        avg_duration = sum(t.get("duration_seconds", 0) for t in completed) / len(completed)
        avg_cost     = sum(t.get("total_cost_usd", 0)  for t in completed) / len(completed)
        avg_score    = sum(t.get("final_eval_score", 0) or 0 for t in completed) / len(completed)

        print(f"\n  PERFORMANCE (completed runs)")
        print(f"  {'Avg duration:':<20} {format_duration(avg_duration)}")
        print(f"  {'Avg cost/run:':<20} {format_cost(avg_cost)}")
        print(f"  {'Avg eval score:':<20} {avg_score:.1f}/10")
        print(f"  {'Total spent:':<20} {format_cost(total_cost)}")
        print(f"  {'Total tokens:':<20} {total_tokens:,}")

    # ── COST PROJECTION ───────────────────────────────────────────────────────
    if completed:
        avg_cost = sum(t.get("total_cost_usd", 0) for t in completed) / len(completed)
        print(f"\n  COST PROJECTION (based on avg {format_cost(avg_cost)}/run)")
        for n in [10, 100, 1000]:
            print(f"  {'  '+str(n)+' runs:':<20} {format_cost(avg_cost * n)}")

    # ── RUN HISTORY ───────────────────────────────────────────────────────────
    print(f"\n  RECENT RUNS")
    print(f"  {'Run ID':<30} {'Niche':<30} {'Score':<8} {'Cost':<8} {'Status'}")
    print(f"  {'-'*30} {'-'*30} {'-'*8} {'-'*8} {'-'*10}")

    for trace in traces[:15]:
        run_id    = trace.get("run_id", "")[-12:]
        niche     = trace.get("niche", "")[:28]
        score     = trace.get("final_eval_score")
        score_str = f"{score}/10" if score is not None else "—"
        cost      = format_cost(trace.get("total_cost_usd", 0))
        status    = trace.get("status", "unknown")
        status_icon = {"completed": "✓", "stopped": "⊘", "stopped_by_gate": "⊘", "failed": "✗"}.get(status, "?")

        print(f"  {run_id:<30} {niche:<30} {score_str:<8} {cost:<8} {status_icon} {status}")

    # ── QUALITY BREAKDOWN ─────────────────────────────────────────────────────
    if completed:
        print(f"\n  QUALITY BREAKDOWN (completed runs)")

        # Count improvement agent usage
        multi_attempt = [
            t for t in completed
            if any(s.get("stage") == "improvement" for s in t.get("stages", []))
        ]
        print(f"  Runs needing improvement agent: {len(multi_attempt)}/{len(completed)}")

        scores = [t.get("final_eval_score") for t in completed if t.get("final_eval_score")]
        if scores:
            print(f"  Score distribution:")
            for threshold, label in [(9, "Excellent (9-10)"), (7, "Good (7-8)"), (5, "Acceptable (5-6)"), (0, "Poor (<5)")]:
                count = sum(1 for s in scores if s >= threshold and (threshold == 9 or s < threshold + 2))
                bar = "█" * count
                print(f"    {label:<20} {bar} {count}")

    # ── TOOL PERFORMANCE ──────────────────────────────────────────────────────
    tool_durations: dict[str, list[float]] = {}

    for trace in traces:
        for stage in trace.get("stages", []):
            for tc in stage.get("tool_calls", []):
                tool = tc.get("tool", "unknown")
                duration = tc.get("duration_ms", 0)
                tool_durations.setdefault(tool, []).append(duration)

    if tool_durations:
        print(f"\n  TOOL PERFORMANCE")
        for tool, durations in sorted(tool_durations.items()):
            avg_ms = sum(durations) / len(durations)
            max_ms = max(durations)
            calls  = len(durations)
            errors = sum(1 for t in traces
                        for s in t.get("stages", [])
                        for tc in s.get("tool_calls", [])
                        if tc.get("tool") == tool and not tc.get("success", True))

            print(f"  {tool:<25} calls:{calls:<6} avg:{avg_ms:>6.0f}ms  max:{max_ms:>6.0f}ms  errors:{errors}")

    # ── STAGE COST BREAKDOWN ──────────────────────────────────────────────────
    if completed:
        stage_costs: dict[str, list[float]] = {}
        for trace in completed:
            for stage in trace.get("stages", []):
                name = stage.get("stage", "unknown")
                cost = stage.get("cost_usd", 0)
                stage_costs.setdefault(name, []).append(cost)

        if stage_costs:
            print(f"\n  COST BY STAGE (avg per run)")
            total_stage_cost = sum(
                sum(costs) / len(costs)
                for costs in stage_costs.values()
            )
            for stage_name, costs in sorted(stage_costs.items()):
                avg = sum(costs) / len(costs)
                pct = (avg / total_stage_cost * 100) if total_stage_cost > 0 else 0
                bar = "█" * int(pct / 5)
                print(f"  {stage_name:<15} {format_cost(avg):<10} {bar} {pct:.0f}%")

    # ── GATE DECISIONS ────────────────────────────────────────────────────────
    gate_actions: dict[str, int] = {}
    for trace in traces:
        for stage in trace.get("stages", []):
            gate = stage.get("gate_decision")
            if gate:
                key = f"{gate.get('gate', 'unknown')}.{gate.get('action', 'unknown')}"
                gate_actions[key] = gate_actions.get(key, 0) + 1

    if gate_actions:
        print(f"\n  GATE DECISIONS (all runs)")
        for key, count in sorted(gate_actions.items(), key=lambda x: -x[1]):
            print(f"  {key:<40} {count}")

    print(f"\n{'='*65}\n")


def show_trace_detail(run_id: str) -> None:
    """Show full detail for a specific run."""
    traces = load_traces()
    match = [t for t in traces if run_id in t.get("run_id", "")]

    if not match:
        print(f"No trace found matching: {run_id}")
        return

    trace = match[0]
    print(f"\n{'='*65}")
    print(f"  TRACE DETAIL: {trace['run_id']}")
    print(f"{'='*65}")
    print(f"  Niche:    {trace.get('niche')}")
    print(f"  Status:   {trace.get('status')}")
    print(f"  Duration: {format_duration(trace.get('duration_seconds', 0))}")
    print(f"  Cost:     {format_cost(trace.get('total_cost_usd', 0))}")
    print(f"  Tokens:   {trace.get('total_tokens_input', 0) + trace.get('total_tokens_output', 0):,}")

    if trace.get("error"):
        print(f"\n  ERROR: {trace['error']}")

    for stage in trace.get("stages", []):
        print(f"\n  ── STAGE: {stage['stage'].upper()} (attempt {stage['attempt']}) ──")
        print(f"     Duration: {format_duration(stage.get('duration_seconds', 0))}")
        print(f"     Tokens:   {stage.get('tokens_input', 0) + stage.get('tokens_output', 0):,}")
        print(f"     Cost:     {format_cost(stage.get('cost_usd', 0))}")

        if stage.get("eval_score") is not None:
            print(f"     Eval:     {stage['eval_score']}/10")

        for tc in stage.get("tool_calls", []):
            status = "✓" if tc.get("success") else "✗"
            extra = ""
            if tc.get("results_count") is not None:
                extra = f" → {tc['results_count']} results"
            if tc.get("chars_returned") is not None:
                extra = f" → {tc['chars_returned']:,} chars"
            if tc.get("error"):
                extra = f" ERROR: {tc['error']}"
            print(f"     {status} {tc['tool']:<25} {tc.get('duration_ms', 0):.0f}ms{extra}")

        gate = stage.get("gate_decision")
        if gate:
            print(f"     Gate ({gate['gate']}): {gate['action'].upper()} — {gate['reason']}")

    print(f"\n{'='*65}\n")


def main():
    parser = argparse.ArgumentParser(description="Pipeline observability dashboard")
    parser.add_argument("--last", type=int, default=None, help="Show last N runs only")
    parser.add_argument("--niche", type=str, default=None, help="Filter by niche")
    parser.add_argument("--detail", type=str, default=None, help="Show full detail for a run ID")
    args = parser.parse_args()

    if args.detail:
        show_trace_detail(args.detail)
        return

    traces = load_traces(last_n=args.last, niche_filter=args.niche)
    show_dashboard(traces)


if __name__ == "__main__":
    main()
