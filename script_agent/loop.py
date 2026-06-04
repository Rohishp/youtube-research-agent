# script_agent/loop.py
#
# The Script Writing Agent loop.
#
# ── KEY ARCHITECTURAL POINT ──────────────────────────────────────────────────
# This agent has NO TOOLS.
#
# The Research Agent needed tools because it had to go out into the world
# and gather information it didn't have. It needed YouTube search and
# transcript fetching.
#
# The Script Agent already has everything it needs — the research brief
# contains the niche analysis, content gaps, video ideas, and tone profile.
# Its job is pure reasoning and creation, not information gathering.
#
# This is why the loop here is simpler: one API call, parse the output, done.
# No while loop needed. No tool execution. Just: context in → script out.
#
# This teaches an important principle: not every agent needs tools.
# Tools are for agents that need to interact with the world.
# Some agents just need good context and clear instructions.
# ─────────────────────────────────────────────────────────────────────────────

import json
import re
from openai import OpenAI
from script_agent.prompts import SCRIPT_SYSTEM_PROMPT, build_script_prompt
from models.schemas import ResearchBrief, VideoScript


MODEL = "gpt-4o"      # Script writing benefits from gpt-4o's stronger reasoning
                       # Switch to gpt-4o-mini to save credits during development

client = OpenAI()


def run_script_agent(brief: ResearchBrief) -> VideoScript:
    """
    Generate a complete video script from a research brief.

    Takes a ResearchBrief (output of Agent 1) and returns a VideoScript.
    This is the handoff point between the two agents.

    The brief is serialized to JSON before being passed to the model.
    Why JSON and not a human-readable summary? Because JSON preserves
    every field exactly — view counts, exact gap titles, exact tone words.
    A summary loses information. The model is good at reading structured data.
    """
    print("\n[Script Agent] Starting script generation...")
    print(f"[Script Agent] Niche: {brief.niche}")
    print(f"[Script Agent] Working from {len(brief.content_gaps)} gaps and {len(brief.video_ideas)} ideas")

    # Serialize the brief to JSON — this becomes the agent's context
    brief_json = json.dumps(brief.model_dump(), indent=2, ensure_ascii=False)
    print(f"[Script Agent] Brief size: {len(brief_json):,} characters passed as context")

    messages = [
        {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
        {"role": "user",   "content": build_script_prompt(brief_json)},
    ]

    print("[Script Agent] Calling model (this may take 30-60 seconds for a full script)...")

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=4096,    # Scripts are long — we need the full token budget
        temperature=0.7,    # Small amount of creativity for the writing
                            # Research agent uses default (1.0) for exploration
                            # Script agent uses 0.7 for more focused creative output
    )

    message = response.choices[0].message
    finish_reason = response.choices[0].finish_reason

    print(f"[Script Agent] Finish reason: {finish_reason}")

    if finish_reason == "length":
        # Script was cut off — the model ran out of tokens mid-generation
        # This means the script is incomplete. Options:
        # 1. Increase max_tokens (costs more)
        # 2. Ask for a shorter script in the prompt
        # 3. Use gpt-4o which handles long outputs better
        print("[Script Agent] WARNING: Output was cut off at token limit.")
        print("[Script Agent] The script may be incomplete.")
        print("[Script Agent] Try reducing requested video length in the prompt,")
        print("[Script Agent] or increase max_tokens in script_agent/loop.py")

    raw_output = message.content or ""
    print(f"[Script Agent] Raw output length: {len(raw_output):,} characters")

    return parse_script_output(raw_output, brief.niche)


def parse_script_output(text: str, niche: str) -> VideoScript:
    """
    Parse the script agent's output into a validated VideoScript.

    Uses the same 3-strategy extraction approach as the research agent:
    1. Extract from markdown code fence
    2. Find first { and last } in the text
    3. Try raw text
    """
    text = text.strip()
    json_str = None

    # Strategy 1: JSON inside markdown code fence
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        json_str = fence_match.group(1)
        print("[Script Parser] Extracted JSON from markdown fence")

    # Strategy 2: Find the JSON object by braces
    if json_str is None:
        first_brace = text.find('{')
        last_brace  = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace:last_brace + 1]
            print("[Script Parser] Extracted JSON by brace detection")

    # Strategy 3: Raw text
    if json_str is None:
        json_str = text
        print("[Script Parser] Attempting to parse raw text")

    try:
        data = json.loads(json_str)
        script = VideoScript(**data)
        print(f"[Script Parser] ✓ Successfully parsed VideoScript")
        print(f"[Script Parser]   Title: {script.seo.title}")
        print(f"[Script Parser]   Sections: {len(script.sections)}")
        print(f"[Script Parser]   Word count: {script.word_count}")
        print(f"[Script Parser]   Duration: {script.estimated_duration_minutes} minutes")
        return script
    except json.JSONDecodeError as e:
        print(f"[Script Parser] ✗ JSON parse error: {e}")
        print(f"[Script Parser] Raw output (first 500 chars):\n{text[:500]}")
        raise ValueError(f"Script agent output was not valid JSON: {e}") from e
    except Exception as e:
        print(f"[Script Parser] ✗ Schema validation error: {e}")
        # Print which fields are missing or wrong
        print(f"[Script Parser] This usually means a field is missing or wrong type.")
        print(f"[Script Parser] Check that the model output includes all required fields.")
        raise ValueError(f"Script output did not match VideoScript schema: {e}") from e
