# YouTube Research & Script Writing Pipeline

A multi-agent AI pipeline that takes a YouTube niche keyword and produces a complete, production-ready video script. Built with the OpenAI API using raw tool calling — no LangChain, no LangGraph abstractions.

## What It Does

```
"morning routines for entrepreneurs"
              ↓
    ┌─────────────────────┐
    │   Research Agent    │  searches YouTube, reads transcripts,
    │                     │  identifies content gaps
    └─────────────────────┘
              ↓  ResearchBrief (JSON)
    ┌─────────────────────┐
    │  Script Writing     │  picks best opportunity, writes
    │     Agent           │  full script with SEO package
    └─────────────────────┘
              ↓
    research_brief.json + video_script.json + readable_script.txt
```

**Pipeline runs in ~60 seconds. No human input required after the niche keyword.**

## Real Output

Running `python main.py "morning routines for entrepreneurs"`:

```
PIPELINE COMPLETE in 56.6s
Niche:           morning routines for entrepreneurs
Opportunity:     8/10
Video title:     Why Most Morning Routines Fail for Entrepreneurs and How to Fix Them
Script length:   1800 words / 12.0 min
Sections:        7
Addresses gap:   Tailored Routines for Different Types of Entrepreneurs
```

Script eval score: **7/10** (hook quality, title specificity, structure, visual direction, length accuracy)

See [`examples/sample_research_brief.json`](examples/sample_research_brief.json) and [`examples/sample_video_script.txt`](examples/sample_video_script.txt) for full outputs.

## Architecture

### Why no LangChain?

The agent loop in `agent/loop.py` is explicit Python. Every decision the model makes is visible and debuggable. I also implemented the same agent in LangGraph (`langgraph_research_agent.py`) to understand framework trade-offs. The raw loop is better for a single agent. LangGraph is worth it for a 10+ agent system where state persistence and checkpointing matter.

### The Core Loop

```python
messages = [system_prompt, user_request]

while True:
    response = openai.chat.completions.create(messages=messages, tools=TOOLS)

    if response.finish_reason == "stop":
        return parse_output(response)          # done

    if response.finish_reason == "tool_calls":
        for tool_call in response.tool_calls:
            result = execute_tool(tool_call)   # search YouTube or get transcript
            messages.append(tool_result)       # agent sees the result
        # loop — agent decides what to do next
```

### Project Structure

```
youtube-research-agent/
├── main.py                      # 3 modes: pipeline / research-only / script-only
├── orchestrator.py              # Connects Research Agent → Script Agent
├── agent/                       # Research Agent
│   ├── loop.py                  # Core agent loop
│   ├── tools.py                 # Tool schemas
│   └── prompts.py               # System prompt
├── script_agent/                # Script Writing Agent
│   ├── loop.py                  # No-tool loop with streaming
│   └── prompts.py               # Script quality rules
├── tools/
│   ├── youtube_search.py        # YouTube Data API v3
│   ├── transcript.py            # Transcript extraction (v1.2.4)
│   └── transcript_store.py      # Saves transcripts for RAG agent
├── models/schemas.py            # Pydantic: ResearchBrief + VideoScript
├── evals/
│   ├── run_evals.py             # Research eval suite
│   └── eval_script.py           # Script quality scorer
├── langgraph_research_agent.py  # LangGraph comparison implementation
└── examples/                    # Sample pipeline outputs
```

## Setup

```bash
git clone https://github.com/Rohishp/youtube-research-agent
cd youtube-research-agent
pip install -r requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY and YOUTUBE_API_KEY to .env
```

```bash
python main.py "morning routines for entrepreneurs"
python main.py "stoic philosophy for modern life" --research-only
python main.py "stoic philosophy" --brief output/brief_stoic_xyz.json
```

## Eval System

```bash
python evals/eval_script.py --script output/script_xyz.json
python evals/run_evals.py --smoke
```

Scoring criteria: hook quality, title specificity, structure completeness, visual direction, length accuracy.

## Key Design Decisions

**Transcript persistence** — Every fetched transcript is saved to `output/transcripts/`. The companion [YouTube RAG Agent](https://github.com/Rohishp/youtube-rag-agent) ingests these into a ChromaDB vector store. Knowledge compounds across research sessions.

**Streaming** — Script agent uses `stream=True`. Tokens appear in real time.

**Pydantic validation** — Output validated against schemas. Malformed output fails loudly rather than silently returning garbage.

**Prompt iteration** — System prompt improved through documented eval cycles. Commit history shows before/after quality scores.

## Connection to YouTube RAG Agent

```
Research Agent (this repo)     →    YouTube RAG Agent
fetches live data each run          queries accumulated knowledge

output/transcripts/*.json      →    ChromaDB vector store
                                    semantic retrieval across all
                                    previously researched niches
```

See [youtube-rag-agent](https://github.com/Rohishp/youtube-rag-agent).

## Tech Stack

OpenAI API (gpt-4o, tool calling, streaming) · YouTube Data API v3 · youtube-transcript-api 1.2.4 · Pydantic v2 · LangGraph (comparison study)
