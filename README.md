# YouTube Niche Research Agent

An agentic AI system that autonomously researches YouTube niches and produces structured content strategy briefs. Built with the Anthropic API using raw tool calling — no frameworks.

## What It Does

Give it a niche keyword. It will:

1. **Search YouTube** for top-performing videos (YouTube Data API v3)
2. **Read transcripts** of the most-viewed videos to understand structure and language
3. **Identify content gaps** — topics audiences want but creators aren't covering
4. **Generate video ideas** with hooks, target emotions, and competition analysis
5. **Produce a structured JSON brief** you can immediately act on

## Example Output

```
RESEARCH BRIEF: MORNING ROUTINES FOR ENTREPRENEURS
============================================================
Opportunity Score: 7/10
Reasoning: High search volume with established creators, but significant gaps in
           actionable content for founders specifically (vs generic productivity)

Key Themes:
  • 5am wake-up routines
  • Deep work blocks
  • Exercise and mental clarity

Content Gaps Found: 4
  • "Morning routines that actually work when you have a team to manage"
  • "The $0 morning routine vs the $500 morning routine — what actually matters"

Video Ideas Generated: 5
  • "I Tested 7 CEO Morning Routines for 30 Days. Here's What Happened"
  • "Why Your Morning Routine Is Failing (It's Not What You Think)"
```

## Architecture

This project demonstrates a production-grade agentic loop without relying on frameworks like LangChain. The core loop is ~60 lines of Python:

```
User Input
    ↓
Agent Loop (agent/loop.py)
    ↓
Claude API (with tool schemas)
    ↓ ← tool_use
Execute Tool (YouTube Search / Transcript)
    ↓ ← tool_result
Claude API (sees result, decides next action)
    ↓ ← end_turn
Parse Structured Output (Pydantic)
    ↓
JSON Research Brief
```

**Why no LangChain?** Understanding the raw loop first makes you a better agent engineer. Frameworks add abstraction; this project adds understanding.

## Project Structure

```
youtube-research-agent/
├── main.py                  # Entry point
├── agent/
│   ├── loop.py             # The core agent loop — read this first
│   ├── tools.py            # Tool schemas passed to the API
│   └── prompts.py          # System prompt and user prompt builders
├── tools/
│   ├── youtube_search.py   # YouTube Data API v3 integration
│   └── transcript.py       # Transcript extraction
├── models/
│   └── schemas.py          # Pydantic models for structured output
└── evals/
    └── run_evals.py        # Automated eval suite across 5 niches
```

## Setup

**1. Clone and install dependencies**
```bash
git clone https://github.com/YOUR_USERNAME/youtube-research-agent
cd youtube-research-agent
pip install -r requirements.txt
```

**2. Set up API keys**
```bash
cp .env.example .env
# Edit .env and add your keys
```

You need two API keys:
- **Anthropic API key**: [console.anthropic.com](https://console.anthropic.com)
- **YouTube Data API v3 key**: [Google Cloud Console](https://console.cloud.google.com) → Enable YouTube Data API v3 → Create credentials

**3. Load environment variables**
```bash
export $(cat .env | xargs)
```

**4. Run**
```bash
python main.py "morning routines for entrepreneurs"
python main.py "stoic philosophy for modern life"
python main.py "beginner investing mistakes"
```

**5. Run the eval suite**
```bash
python evals/run_evals.py --smoke    # Quick test (1 niche)
python evals/run_evals.py            # Full suite (5 niches)
```

## Key Design Decisions

**Raw API over frameworks** — The agent loop in `agent/loop.py` is explicit Python. Every decision the agent makes is visible and debuggable. No magic.

**Pydantic for structured output** — The agent's final output is validated against a schema. If it doesn't conform, it fails loudly rather than silently returning garbage.

**Evals as first-class artifacts** — `evals/run_evals.py` scores output quality on 5 criteria across 5 test niches. This is how you know changes to prompts actually improve results.

**Context window awareness** — Transcripts are capped at 8,000 characters. Multiple videos × full transcripts would overflow the context window mid-task.

**Graceful tool failure** — Tools return error dicts instead of raising exceptions. The agent decides what to do when a tool fails, rather than crashing.

## Extending This Project

Natural next steps:
- Add a `search_competitor_channels` tool
- Add a `get_comment_sentiment` tool to understand audience reaction
- Chain into a Script Writing Agent that uses this brief as input
- Add a vector store to avoid re-researching the same niches

## Tech Stack

- **Anthropic API** — claude-sonnet-4 with tool calling
- **YouTube Data API v3** — video search and metadata
- **youtube-transcript-api** — transcript extraction
- **Pydantic v2** — structured output validation

---

*Built as part of learning production agentic AI systems. See `agent/loop.py` for the core implementation.*
