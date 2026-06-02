# agent/loop.py
#
# THIS IS THE MOST IMPORTANT FILE IN THE PROJECT.
# Read it carefully. This IS what an agent is.
#
# The agent loop:
# 1. Send the task + available tools to the model
# 2. Model decides: "I need to call a tool" OR "I'm done, here's my answer"
# 3. If tool call: execute it, add the result to the conversation, go to step 1
# 4. If done: parse the final output and return it
#
# ── KEY DIFFERENCE vs Anthropic API ──────────────────────────────────────────
# Anthropic:  system prompt is a separate parameter outside messages[]
#             tool results go as a "user" role message with type="tool_result"
#             stop reasons: "end_turn" | "tool_use"
#
# OpenAI:     system prompt is the FIRST message in messages[] with role="system"
#             tool results go as their OWN message with role="tool"
#             stop reasons: "stop" | "tool_calls"
#
# Same concept, different wire format. The loop logic is identical.
# ─────────────────────────────────────────────────────────────────────────────

import json
from openai import OpenAI
from agent.tools import TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from tools.youtube_search import search_youtube
from tools.transcript import get_transcript
from models.schemas import ResearchBrief


# gpt-4o is the best choice for agents — strong tool-calling decisions.
# gpt-4o-mini works too and is 10x cheaper, but makes worse multi-step decisions.
# Switch to "gpt-4o-mini" if you want to save credits during development.
MODEL = "gpt-4o"

# Initialize the OpenAI client once at module level.
# It automatically reads OPENAI_API_KEY from the environment.
client = OpenAI()


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """
    Route a tool call to the correct Python function and return the result as a string.

    Why return a string? Because the OpenAI API expects tool results as text content.
    We serialize the result to JSON so it's structured and readable by the model.

    If a tool fails, we return an error message instead of raising an exception.
    This is important: we want the AGENT to decide what to do when a tool fails,
    not have the whole program crash.
    """
    print(f"  → Calling tool: {tool_name}({json.dumps(tool_input, indent=2)})")

    try:
        if tool_name == "search_youtube":
            result = search_youtube(
                query=tool_input["query"],
                max_results=tool_input.get("max_results", 10)
            )
        elif tool_name == "get_transcript":
            result = get_transcript(video_id=tool_input["video_id"])
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        result_str = json.dumps(result, ensure_ascii=False)

        preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
        print(f"  ← Tool result preview: {preview}")

        return result_str

    except Exception as e:
        error_msg = f"Tool execution failed: {str(e)}"
        print(f"  ✗ {error_msg}")
        return json.dumps({"error": error_msg})


def run_agent(niche: str, max_iterations: int = 20) -> ResearchBrief:
    """
    Run the research agent for a given niche.

    OpenAI conversation structure grows like this:

        [system]                    ← instructions, never changes
        [user]                      ← the research request
        [assistant + tool_calls]    ← model decides to search YouTube
        [tool]                      ← search result comes back
        [tool]                      ← (if multiple tools called in one turn)
        [assistant + tool_calls]    ← model decides to get a transcript
        [tool]                      ← transcript comes back
        ... (repeats until done)
        [assistant]                 ← model writes final JSON brief

    The key insight: we are the memory. The model has no state between calls.
    We pass the entire conversation every single time.
    """
    print(f"\n{'='*60}")
    print(f"Starting research agent for niche: '{niche}'")
    print(f"{'='*60}\n")

    # ── OPENAI DIFFERENCE #1 ─────────────────────────────────────────────────
    # System prompt goes INSIDE messages[] as the first entry with role="system"
    # In Anthropic API it's a separate `system=` parameter outside messages[]
    # ─────────────────────────────────────────────────────────────────────────
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": build_user_prompt(niche)},
    ]

    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n[Iteration {iteration}] Calling {MODEL}...")

        # Call the OpenAI API.
        # We pass the full conversation every time — the model is stateless.
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",   # Model decides when to use tools vs stop
            max_tokens=4096,
        )

        # OpenAI wraps the response in choices[0].
        # In Anthropic API you access response.content directly.
        message = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        print(f"[Iteration {iteration}] Finish reason: {finish_reason}")

        # ── OPENAI DIFFERENCE #2 ─────────────────────────────────────────────
        # We must add the assistant message back to history BEFORE adding tool results.
        # The assistant message may contain both text content AND tool_calls.
        # We rebuild it as a plain dict for clarity.
        # ─────────────────────────────────────────────────────────────────────
        assistant_message = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id":       tc.id,
                    "type":     "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,  # Already a JSON string
                    }
                }
                for tc in message.tool_calls
            ]
        messages.append(assistant_message)

        # ── CASE 1: Model is done ─────────────────────────────────────────────
        # finish_reason == "stop" means the model wrote its final response
        # (equivalent to "end_turn" in Anthropic API)
        if finish_reason == "stop":
            print("\n[Agent] Research complete. Parsing output...")
            return parse_final_output(message.content or "", niche)

        # ── CASE 2: Model wants to use tools ──────────────────────────────────
        # finish_reason == "tool_calls" means the model made one or more tool calls
        # (equivalent to "tool_use" in Anthropic API)
        if finish_reason == "tool_calls" and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name  = tool_call.function.name
                # arguments come back as a JSON string — we parse it to a dict
                tool_input = json.loads(tool_call.function.arguments)

                result = execute_tool(tool_name, tool_input)

                # ── OPENAI DIFFERENCE #3 ─────────────────────────────────────
                # Tool results get their OWN message with role="tool"
                # In Anthropic API they go inside a "user" message as content blocks
                # tool_call_id links this result back to the tool_call that requested it
                # ─────────────────────────────────────────────────────────────
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result,
                })

            # Loop continues — model will see these results and decide next action
            continue

        # ── CASE 3: Unexpected finish reason ──────────────────────────────────
        print(f"[Warning] Unexpected finish reason: {finish_reason}")
        break

    raise RuntimeError(
        f"Agent did not complete within {max_iterations} iterations. "
        "Check your system prompt or increase max_iterations."
    )


def parse_final_output(text: str, niche: str) -> ResearchBrief:
    """
    Parse the agent's final text output into a validated ResearchBrief.

    Models sometimes add explanation text before or after the JSON, or wrap
    it in markdown code fences. We try three extraction strategies in order:
      1. Extract JSON from inside a ```json ... ``` block
      2. Extract the first {...} block found anywhere in the text
      3. Try the raw text as-is
    """
    import re

    text = text.strip()
    json_str = None

    # Strategy 1: JSON inside a markdown code fence (```json ... ``` or ``` ... ```)
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        json_str = fence_match.group(1)
        print("[Parser] Extracted JSON from markdown code fence")

    # Strategy 2: Find the first { and the last } in the whole text
    # This handles cases where the model writes text before/after the JSON
    if json_str is None:
        first_brace = text.find('{')
        last_brace  = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace:last_brace + 1]
            print("[Parser] Extracted JSON by finding first { and last }")

    # Strategy 3: Use the raw text
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
