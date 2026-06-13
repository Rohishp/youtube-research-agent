# agent/loop.py
#
# The core research agent loop — now tracer-aware.
#
# The only change from the previous version:
# - run_agent() accepts an optional `tracer` parameter
# - _execute_tool() records timing and results to the tracer
# - The loop records token usage from every API response
#
# Everything else is identical. The tracer is purely additive —
# if no tracer is passed, the agent runs exactly as before.
# This is the correct way to add observability: don't change the logic,
# just add recording alongside it.

import json
import time
from typing import Optional, TYPE_CHECKING
from openai import OpenAI
from agent.tools import TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from tools.youtube_search import search_youtube
from tools.transcript import get_transcript
from tools.transcript_store import save_transcript
from models.schemas import ResearchBrief

if TYPE_CHECKING:
    from observability.tracer import Tracer

MODEL = "gpt-4o"
client = OpenAI()


def run_agent(
    niche: str,
    max_iterations: int = 20,
    tracer: Optional["Tracer"] = None,
) -> ResearchBrief:
    """
    Run the research agent for a given niche.

    Parameters
    ----------
    niche : str
        The YouTube niche to research.
    max_iterations : int
        Safety limit on agent loop iterations.
    tracer : Tracer, optional
        If provided, records timing, token usage, and tool calls.
        If None, agent runs normally with no observability overhead.
    """
    print(f"\n{'='*60}")
    print(f"Starting research agent for niche: '{niche}'")
    print(f"{'='*60}\n")

    normalised_niche = niche.lower().replace(" ", "_")

    def _execute_tool(tool_name: str, tool_input: dict) -> str:
        print(f"  → Calling tool: {tool_name}({json.dumps(tool_input, indent=2)})")

        # ── TIME THE TOOL CALL ────────────────────────────────────────────────
        # This is your Q1 answer: start timer before, end timer after.
        # perf_counter gives sub-millisecond precision.
        tool_start = time.perf_counter()
        success = True
        error_msg = None
        result = {}

        try:
            if tool_name == "search_youtube":
                result = search_youtube(
                    query=tool_input["query"],
                    max_results=tool_input.get("max_results", 10)
                )
            elif tool_name == "get_transcript":
                result = get_transcript(video_id=tool_input["video_id"])
                if result.get("transcript"):
                    save_transcript(result, niche=normalised_niche)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}
                success = False

            result_str = json.dumps(result, ensure_ascii=False)
            preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
            print(f"  ← Tool result preview: {preview}")

        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            print(f"  ✗ {error_msg}")
            result_str = json.dumps({"error": error_msg})
            success = False

        # ── RECORD TO TRACER ──────────────────────────────────────────────────
        duration_ms = (time.perf_counter() - tool_start) * 1000

        if tracer:
            tracer.record_tool_call(
                tool=tool_name,
                tool_input=tool_input,
                duration_ms=duration_ms,
                success=success,
                error=error_msg,
                results_count=result.get("total_found") if tool_name == "search_youtube" else None,
                chars_returned=result.get("char_count") if tool_name == "get_transcript" else None,
                saved_to_disk=bool(result.get("transcript")) if tool_name == "get_transcript" else None,
            )

        return result_str

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": build_user_prompt(niche)},
    ]

    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n[Iteration {iteration}] Calling {MODEL}...")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=4096,
        )

        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        print(f"[Iteration {iteration}] Finish reason: {finish_reason}")

        # ── RECORD TOKEN USAGE ────────────────────────────────────────────────
        # Every API response includes token counts.
        # We record them so we know what each stage costs.
        if tracer and response.usage:
            tracer.record_tokens(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

        assistant_message = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id":       tc.id,
                    "type":     "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_message)

        if finish_reason == "stop":
            print("\n[Agent] Research complete. Parsing output...")
            return parse_final_output(message.content or "", niche)

        if finish_reason == "tool_calls" and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name  = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                result = _execute_tool(tool_name, tool_input)
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result,
                })
            continue

        print(f"[Warning] Unexpected finish reason: {finish_reason}")
        break

    raise RuntimeError(
        f"Agent did not complete within {max_iterations} iterations."
    )


def parse_final_output(text: str, niche: str) -> ResearchBrief:
    """Parse agent output into a validated ResearchBrief."""
    import re

    text = text.strip()
    json_str = None

    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        json_str = fence_match.group(1)
        print("[Parser] Extracted JSON from markdown code fence")

    if json_str is None:
        first_brace = text.find('{')
        last_brace  = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace:last_brace + 1]
            print("[Parser] Extracted JSON by finding first { and last }")

    if json_str is None:
        json_str = text
        print("[Parser] Attempting to parse raw text as JSON")

    try:
        data = json.loads(json_str)
        brief = ResearchBrief(**data)
        print(f"[Parser] ✓ Successfully parsed research brief for '{niche}'")
        return brief
    except json.JSONDecodeError as e:
        print(f"[Parser] ✗ JSON parse error: {e}")
        print(f"[Parser] Raw text (first 500 chars): {text[:500]}")
        raise ValueError(f"Agent output was not valid JSON: {e}") from e
    except Exception as e:
        print(f"[Parser] ✗ Schema validation error: {e}")
        raise ValueError(f"Agent output did not match expected schema: {e}") from e
