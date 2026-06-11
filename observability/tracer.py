# observability/tracer.py
#
# Records every pipeline run as a structured JSON trace.
#
# A Tracer instance is created at the start of each pipeline run.
# It collects events as the pipeline executes:
#   - tool calls (name, input, duration, success)
#   - stage boundaries (research started, script started)
#   - gate decisions (which gate, what score, what action)
#   - token usage (from OpenAI API responses)
#
# At the end of the run — success OR failure — it writes a JSON file.
# That file is the permanent record of what happened.
#
# WHY THIS MATTERS
# ─────────────────
# Without tracing:
#   - Debug by reading terminal output (gone when window closes)
#   - No way to compare runs over time
#   - No cost visibility
#   - "Why did that fail?" requires re-running
#
# With tracing:
#   - Every run has a permanent, searchable record
#   - Compare 20 runs in a single script
#   - Know exactly what a run cost
#   - Debug by reading the trace file, not re-running

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# GPT-4o pricing (as of June 2026)
# Source: platform.openai.com/pricing
# These are approximate — update if pricing changes
GPT4O_INPUT_COST_PER_1K  = 0.005   # $5.00 per 1M input tokens
GPT4O_OUTPUT_COST_PER_1K = 0.015   # $15.00 per 1M output tokens

TRACES_DIR = Path("output/traces")


@dataclass
class ToolCallRecord:
    """Record of a single tool call."""
    tool: str
    input_summary: dict        # Key fields only — not the full result
    duration_ms: float
    success: bool
    error: Optional[str] = None
    # Tool-specific fields
    results_count: Optional[int] = None      # search_youtube
    chars_returned: Optional[int] = None     # get_transcript
    saved_to_disk: Optional[bool] = None     # get_transcript


@dataclass
class GateRecord:
    """Record of a gate decision."""
    gate: str
    action: str                # proceed / retry / stop
    reason: str
    detail: str = ""
    # Gate-specific context
    opportunity_score: Optional[int] = None
    videos_analyzed: Optional[int] = None
    gaps_found: Optional[int] = None
    eval_score: Optional[int] = None


@dataclass
class StageRecord:
    """Record of one pipeline stage (research or script)."""
    stage: str                 # "research" or "script" or "improvement"
    attempt: int
    started_at: str
    duration_seconds: float = 0.0
    iterations: int = 0
    tool_calls: list = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    eval_score: Optional[int] = None
    gate_decision: Optional[GateRecord] = None
    error: Optional[str] = None


class Tracer:
    """
    Collects trace events during a pipeline run and writes a JSON record.

    Usage:
        tracer = Tracer(niche="morning routines")
        tracer.start_stage("research", attempt=1)
        tracer.record_tool_call(...)
        tracer.record_tokens(input=1200, output=800)
        tracer.end_stage()
        tracer.record_gate(gate_decision, brief=brief)
        tracer.finish(status="completed", eval_score=7, title="...")
        tracer.save()
    """

    def __init__(self, niche: str):
        self.run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.niche = niche
        self.started_at = datetime.now().isoformat()
        self._pipeline_start = time.perf_counter()
        self.stages: list[StageRecord] = []
        self._current_stage: Optional[StageRecord] = None
        self._stage_start: Optional[float] = None
        self.status = "running"
        self.final_eval_score: Optional[int] = None
        self.final_title: Optional[str] = None
        self.warnings: list[str] = []
        self.error: Optional[str] = None

        print(f"[Tracer] Run ID: {self.run_id}")

    # ── Stage management ──────────────────────────────────────────────────────

    def start_stage(self, stage: str, attempt: int = 1):
        """Mark the beginning of a pipeline stage."""
        self._current_stage = StageRecord(
            stage=stage,
            attempt=attempt,
            started_at=datetime.now().isoformat(),
        )
        self._stage_start = time.perf_counter()

    def end_stage(self):
        """Mark the end of the current stage and record its duration."""
        if self._current_stage and self._stage_start:
            self._current_stage.duration_seconds = round(
                time.perf_counter() - self._stage_start, 2
            )
            self.stages.append(self._current_stage)
            self._current_stage = None
            self._stage_start = None

    # ── Event recording ───────────────────────────────────────────────────────

    def record_tool_call(
        self,
        tool: str,
        tool_input: dict,
        duration_ms: float,
        success: bool,
        error: str = None,
        results_count: int = None,
        chars_returned: int = None,
        saved_to_disk: bool = None,
    ):
        """Record a tool call that happened during the current stage."""
        if not self._current_stage:
            return

        # Summarise input — don't store full results (too large)
        input_summary = {}
        if "query" in tool_input:
            input_summary["query"] = tool_input["query"]
        if "video_id" in tool_input:
            input_summary["video_id"] = tool_input["video_id"]
        if "max_results" in tool_input:
            input_summary["max_results"] = tool_input["max_results"]

        record = ToolCallRecord(
            tool=tool,
            input_summary=input_summary,
            duration_ms=round(duration_ms, 1),
            success=success,
            error=error,
            results_count=results_count,
            chars_returned=chars_returned,
            saved_to_disk=saved_to_disk,
        )
        self._current_stage.tool_calls.append(record)
        self._current_stage.iterations += 1

    def record_tokens(self, input_tokens: int, output_tokens: int):
        """
        Record token usage from an API response.
        Automatically calculates cost.
        """
        if not self._current_stage:
            return
        self._current_stage.tokens_input += input_tokens
        self._current_stage.tokens_output += output_tokens

        # Calculate cost for this call
        cost = (
            (input_tokens / 1000) * GPT4O_INPUT_COST_PER_1K +
            (output_tokens / 1000) * GPT4O_OUTPUT_COST_PER_1K
        )
        self._current_stage.cost_usd += cost

    def record_gate(self, decision, brief=None, eval_score: int = None):
        """Record a gate decision for the current stage."""
        if not self._current_stage:
            return

        gate_record = GateRecord(
            gate="niche_gate" if brief else "script_gate",
            action=decision.action,
            reason=decision.reason,
            detail=decision.detail,
            eval_score=eval_score,
        )

        # Add brief-specific context for niche gate
        if brief:
            gate_record.gate = "niche_gate"
            gate_record.opportunity_score = brief.opportunity_score
            gate_record.videos_analyzed = len(brief.top_videos_analyzed)
            gate_record.gaps_found = len(brief.content_gaps)
        else:
            gate_record.gate = "script_gate"

        self._current_stage.gate_decision = gate_record

    def record_stage_eval(self, eval_score: int):
        """Record the eval score for the current stage."""
        if self._current_stage:
            self._current_stage.eval_score = eval_score

    def record_warning(self, warning: str):
        """Record a quality warning."""
        self.warnings.append(warning)

    def record_error(self, error: str):
        """Record that the pipeline failed with an error."""
        self.status = "failed"
        self.error = error
        if self._current_stage:
            self._current_stage.error = error
            self.end_stage()

    # ── Finalise and save ─────────────────────────────────────────────────────

    def finish(self, status: str, eval_score: int = None, title: str = None):
        """Mark the pipeline as complete."""
        self.status = status
        self.final_eval_score = eval_score
        self.final_title = title
        if self._current_stage:
            self.end_stage()

    def save(self) -> Path:
        """
        Write the trace to disk as a JSON file.
        Called in a finally block — runs whether pipeline succeeded or failed.
        """
        TRACES_DIR.mkdir(parents=True, exist_ok=True)

        total_duration = round(time.perf_counter() - self._pipeline_start, 2)
        total_tokens_input  = sum(s.tokens_input  for s in self.stages)
        total_tokens_output = sum(s.tokens_output for s in self.stages)
        total_cost = sum(s.cost_usd for s in self.stages)

        trace = {
            "run_id": self.run_id,
            "niche": self.niche,
            "status": self.status,
            "started_at": self.started_at,
            "duration_seconds": total_duration,
            "total_tokens_input": total_tokens_input,
            "total_tokens_output": total_tokens_output,
            "total_cost_usd": round(total_cost, 4),
            "final_eval_score": self.final_eval_score,
            "final_title": self.final_title,
            "warnings": self.warnings,
            "error": self.error,
            "stages": [self._serialise_stage(s) for s in self.stages],
        }

        path = TRACES_DIR / f"{self.run_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2, ensure_ascii=False)

        print(f"\n[Tracer] Trace saved: {path}")
        print(f"[Tracer] Duration: {total_duration}s | "
              f"Tokens: {total_tokens_input + total_tokens_output:,} | "
              f"Cost: ${total_cost:.4f}")

        return path

    def _serialise_stage(self, stage: StageRecord) -> dict:
        """Convert a StageRecord to a JSON-serialisable dict."""
        gate = None
        if stage.gate_decision:
            g = stage.gate_decision
            gate = {
                "gate": g.gate,
                "action": g.action,
                "reason": g.reason,
                "detail": g.detail,
            }
            if g.opportunity_score is not None:
                gate["opportunity_score"] = g.opportunity_score
            if g.videos_analyzed is not None:
                gate["videos_analyzed"] = g.videos_analyzed
            if g.gaps_found is not None:
                gate["gaps_found"] = g.gaps_found
            if g.eval_score is not None:
                gate["eval_score"] = g.eval_score

        return {
            "stage": stage.stage,
            "attempt": stage.attempt,
            "started_at": stage.started_at,
            "duration_seconds": stage.duration_seconds,
            "iterations": stage.iterations,
            "tokens_input": stage.tokens_input,
            "tokens_output": stage.tokens_output,
            "cost_usd": round(stage.cost_usd, 4),
            "eval_score": stage.eval_score,
            "gate_decision": gate,
            "error": stage.error,
            "tool_calls": [
                {
                    "tool": tc.tool,
                    "input": tc.input_summary,
                    "duration_ms": tc.duration_ms,
                    "success": tc.success,
                    "error": tc.error,
                    **({"results_count": tc.results_count} if tc.results_count is not None else {}),
                    **({"chars_returned": tc.chars_returned} if tc.chars_returned is not None else {}),
                    **({"saved_to_disk": tc.saved_to_disk} if tc.saved_to_disk is not None else {}),
                }
                for tc in stage.tool_calls
            ],
        }
