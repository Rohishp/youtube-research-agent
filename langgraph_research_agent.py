# langgraph_research_agent.py
#
# The same research agent you already built — re-implemented in LangGraph.
#
# PURPOSE OF THIS FILE
# Not to replace your working agent. To teach you what LangGraph abstracts
# by showing you the same logic expressed differently.
#
# Read this alongside agent/loop.py. Every section has a comment explaining
# what the raw loop does vs what LangGraph does.
#
# After running both, answer these three questions in writing:
#   1. What does LangGraph give you that the raw loop doesn't?
#   2. What does the raw loop give you that LangGraph obscures?
#   3. For a 10-agent production system, which would you choose and why?
#
# Run it:
#   python langgraph_research_agent.py "stoic philosophy for modern life"

import json
import sys
import os
from typing import TypedDict, Annotated
import operator
from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage

# Reuse your existing tools and prompts — nothing changes there
from agent.tools import TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT, build_user_prompt
from tools.youtube_search import search_youtube
from tools.transcript import get_transcript
from tools.transcript_store import save_transcript
from models.schemas import ResearchBrief
import re


# ── STATE ─────────────────────────────────────────────────────────────────────
#
# This is the most important concept in LangGraph.
#
# In your raw loop, state is implicit — it lives in the `messages` list
# you manage manually. You know what's in it because you put it there.
#
# In LangGraph, state is EXPLICIT — you define a TypedDict that describes
# every piece of state the graph needs to track. The framework manages it.
#
# RAW LOOP version (implicit state):
#   messages = [...]
#   while True:
#       response = client.chat.completions.create(messages=messages)
#       messages.append(...)   # you manually update state
#
# LANGGRAPH version (explicit state):
#   class AgentState(TypedDict):
#       messages: list          # framework tracks this
#       niche: str              # framework tracks this
#   graph.invoke({"messages": [...], "niche": "..."})  # framework passes state between nodes
#
# The benefit: in complex multi-agent systems, explicit state is easier to
# inspect, checkpoint, and resume. The cost: more boilerplate for simple agents.
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Annotated[list, operator.add] means: when two states are merged,
    # combine the message lists by appending (not replacing).
    # This is how LangGraph handles message accumulation across nodes.
    messages: Annotated[list, operator.add]
    niche: str


# ── MODEL ─────────────────────────────────────────────────────────────────────
#
# LangGraph uses LangChain's model wrappers instead of the OpenAI SDK directly.
# ChatOpenAI is a thin wrapper around the same API you've been using.
# bind_tools() attaches your tool schemas to the model — equivalent to passing
# tools=TOOL_SCHEMAS in your raw loop's client.chat.completions.create() call.
# ─────────────────────────────────────────────────────────────────────────────

model = ChatOpenAI(model="gpt-4o", max_tokens=4096)
model_with_tools = model.bind_tools(TOOL_SCHEMAS)


# ── NODE 1: CALL MODEL ────────────────────────────────────────────────────────
#
# A "node" in LangGraph is just a function that:
#   - takes the current state
#   - does something
#   - returns a dict with state updates
#
# This node does exactly what your raw loop does at the top of each iteration:
# calls the model with the current message history.
#
# RAW LOOP equivalent:
#   response = client.chat.completions.create(
#       model=MODEL, messages=messages, tools=TOOL_SCHEMAS
#   )
# ─────────────────────────────────────────────────────────────────────────────

def call_model(state: AgentState) -> dict:
    """Send current messages to the model and get a response."""
    print(f"\n[LangGraph] Calling model... ({len(state['messages'])} messages in context)")

    response = model_with_tools.invoke(state["messages"])

    print(f"[LangGraph] Response type: {type(response).__name__}")
    if hasattr(response, 'tool_calls') and response.tool_calls:
        tool_names = [tc['name'] for tc in response.tool_calls]
        print(f"[LangGraph] Tool calls requested: {tool_names}")
    else:
        print(f"[LangGraph] No tool calls — model is done")

    # Return state update — LangGraph merges this into the current state
    # The Annotated[list, operator.add] means this appends to messages, not replaces
    return {"messages": [response]}


# ── NODE 2: EXECUTE TOOLS ─────────────────────────────────────────────────────
#
# This node executes whatever tools the model requested.
#
# RAW LOOP equivalent:
#   for tool_call in message.tool_calls:
#       result = execute_tool(tool_call.function.name, json.loads(tool_call.function.arguments))
#       messages.append({"role": "tool", "tool_call_id": ..., "content": result})
#
# The logic is identical. The difference: LangGraph uses ToolMessage objects
# instead of raw dicts. Same data, different wrapper.
# ─────────────────────────────────────────────────────────────────────────────

def execute_tools(state: AgentState) -> dict:
    """Execute all tool calls from the last assistant message."""
    last_message = state["messages"][-1]
    normalised_niche = state["niche"].lower().replace(" ", "_")

    tool_messages = []

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_input = tool_call["args"]
        tool_call_id = tool_call["id"]

        print(f"  → Tool: {tool_name}({json.dumps(tool_input)})")

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

            result_str = json.dumps(result, ensure_ascii=False)
            preview = result_str[:150] + "..." if len(result_str) > 150 else result_str
            print(f"  ← Result: {preview}")

        except Exception as e:
            result_str = json.dumps({"error": str(e)})
            print(f"  ✗ Tool failed: {e}")

        # LangGraph uses ToolMessage — equivalent to {"role": "tool", ...} in raw loop
        tool_messages.append(ToolMessage(
            content=result_str,
            tool_call_id=tool_call_id
        ))

    return {"messages": tool_messages}


# ── ROUTING FUNCTION ──────────────────────────────────────────────────────────
#
# This is the conditional logic that decides what happens next.
#
# RAW LOOP equivalent:
#   if finish_reason == "stop":
#       return parse_final_output(...)   # done
#   elif finish_reason == "tool_calls":
#       # execute tools, loop again
#
# In LangGraph this becomes a function that returns a string — the name of
# the next node to execute, or END to stop.
#
# This explicit routing is one of LangGraph's strengths: the flow of control
# is visible as a graph, not hidden inside a while loop.
# ─────────────────────────────────────────────────────────────────────────────

def should_continue(state: AgentState) -> str:
    """
    Decide what to do after the model responds.
    Returns "tools" to execute tool calls, or "end" to finish.
    """
    last_message = state["messages"][-1]

    # If the model made tool calls, execute them
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # Otherwise the model is done — parse its response
    return "end"


# ── BUILD THE GRAPH ───────────────────────────────────────────────────────────
#
# This is where LangGraph differs most visibly from the raw loop.
# Instead of a while loop with if/elif branches, you define:
#   - nodes (what to do)
#   - edges (what comes next)
#   - conditional edges (what comes next based on a condition)
#
# The resulting graph looks like this:
#
#   START
#     ↓
#   [agent] (call_model)
#     ↓
#   should_continue()
#     ├── "tools" → [tools] (execute_tools) → [agent] (loop back)
#     └── "end"  → END
#
# Compare to your raw loop:
#   while iteration < max_iterations:
#       response = call_llm()
#       if finish_reason == "stop": return
#       if finish_reason == "tool_calls": execute_tools(); continue
#
# Same logic. Different expression.
# The graph is more explicit about structure. The while loop is more explicit
# about the actual execution flow.
# ─────────────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("agent", call_model)
    graph.add_node("tools", execute_tools)

    # Set entry point
    graph.set_entry_point("agent")

    # Add conditional edge from agent: tools or end
    graph.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",   # if should_continue returns "tools" → go to tools node
            "end": END          # if should_continue returns "end" → stop
        }
    )

    # After tools, always go back to agent
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── PARSE OUTPUT ─────────────────────────────────────────────────────────────
# Same parser as your raw loop — nothing changes here

def parse_final_output(text: str, niche: str) -> ResearchBrief:
    text = text.strip()
    fence_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fence_match:
        json_str = fence_match.group(1)
    else:
        first = text.find('{')
        last = text.rfind('}')
        json_str = text[first:last+1] if first != -1 and last != -1 else text

    data = json.loads(json_str.strip())
    return ResearchBrief(**data)


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run_langgraph_agent(niche: str) -> ResearchBrief:
    print(f"\n{'='*60}")
    print(f"LangGraph Research Agent: '{niche}'")
    print(f"{'='*60}\n")

    app = build_graph()

    # Initial state — equivalent to your messages = [...] initialisation
    initial_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=build_user_prompt(niche))
        ],
        "niche": niche
    }

    # invoke() runs the graph to completion
    # Under the hood it's doing exactly what your while loop does
    final_state = app.invoke(initial_state)

    # Get the last message — the model's final response
    last_message = final_state["messages"][-1]
    final_text = last_message.content if hasattr(last_message, 'content') else str(last_message)

    print(f"\n[LangGraph] Graph complete. Parsing output...")
    brief = parse_final_output(final_text, niche)
    print(f"[LangGraph] ✓ Brief parsed. Opportunity score: {brief.opportunity_score}/10")

    return brief


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python langgraph_research_agent.py "your niche here"')
        sys.exit(1)

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    niche = sys.argv[1]
    brief = run_langgraph_agent(niche)

    print(f"\n{'='*60}")
    print(f"RESULT")
    print(f"{'='*60}")
    print(f"Niche:           {brief.niche}")
    print(f"Opportunity:     {brief.opportunity_score}/10")
    print(f"Gaps found:      {len(brief.content_gaps)}")
    print(f"Ideas generated: {len(brief.video_ideas)}")
    print(f"{'='*60}\n")

    # ── REFLECTION PROMPTS ────────────────────────────────────────────────────
    # After running this, compare it to your raw loop and answer these:
    #
    # 1. What does LangGraph give you that agent/loop.py doesn't?
    #    Hint: look at AgentState vs your messages list.
    #    Hint: look at the graph definition vs the while loop.
    #    Hint: think about what would happen if this crashed mid-run.
    #
    # 2. What does agent/loop.py give you that this version obscures?
    #    Hint: where exactly does the model response get added to history here?
    #    Hint: can you see the finish_reason anywhere?
    #
    # 3. For a 10-agent production system, which would you choose?
    #    Hint: think about debugging, state inspection, resuming failed runs.
    #    Hint: think about how much time you'd spend reading framework docs.
    #
    # Write your answers before our next session.
    # ─────────────────────────────────────────────────────────────────────────
