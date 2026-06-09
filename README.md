# YouTube Knowledge Agent (RAG)

A retrieval-augmented generation agent that answers questions about YouTube content strategy using accumulated transcript knowledge. Built with OpenAI embeddings and ChromaDB — no frameworks.

## What It Does

Instead of searching YouTube fresh every time, this agent queries a local vector database of previously analyzed transcripts. Knowledge compounds — every transcript indexed makes future answers richer.

```
You: "What hooks do top stoic philosophy creators use?"

Agent:
  → get_index_stats()          # check what's available
  → retrieve_knowledge(...)    # semantic search, 3 different phrasings
  → synthesize answer with cited sources and confidence level
```

## Real Output

```
ANSWER
Creators of stoic philosophy content commonly employ personal storytelling
as hooks. In '3 Stoic Habits I Practice Every Single Day', the creator opens
with a challenging decade: a failed startup, a divorce, and a health scare —
promising real-life application rather than academic discourse. Similarly,
'Stoic Principles That Changed How I Run My Business' hooks with Marcus
Aurelius's private journal, connecting ancient wisdom to modern entrepreneurship.

KEY INSIGHTS:
  • Personal failure stories outperform abstract philosophy as openers
  • Historical figures (Marcus Aurelius, Seneca, Epictetus) provide credibility anchors
  • Practical framing beats theoretical — "how I use this" over "what this means"

SOURCES: 3 videos cited
CONFIDENCE: HIGH
```

## Why RAG

Context windows have limits. You cannot paste 500 transcripts into a prompt. RAG solves this:
1. Convert every transcript paragraph into a vector (1536 numbers encoding meaning)
2. Store vectors in ChromaDB
3. At query time: find only the paragraphs semantically similar to the question
4. Send only those relevant paragraphs to the LLM

Result: focused, grounded answers instead of hallucinated generalisations.

## Project Structure

```
youtube-rag-agent/
├── main.py              # Ask questions
├── ingest.py            # Load transcripts into knowledge base
├── agent/
│   ├── loop.py          # Agent loop — same pattern as research agent
│   ├── tools.py         # retrieve_knowledge, retrieve_by_niche, get_index_stats
│   └── prompts.py       # System prompt enforcing source citation
├── tools/
│   ├── indexer.py       # Chunking + embedding + ChromaDB storage
│   └── retriever.py     # Semantic search with similarity threshold
└── models/schemas.py    # TranscriptChunk, KnowledgeAnswer (Pydantic)
```

## Setup

```bash
git clone https://github.com/Rohishp/youtube-rag-agent
cd youtube-rag-agent
pip install -r requirements.txt
cp .env.example .env
# Add OPENAI_API_KEY to .env
```

```bash
# Load sample data (no YouTube API needed)
python ingest.py --sample

# Check what's indexed
python ingest.py --stats

# Ask questions
python main.py "What hooks do top morning routine creators use?"
python main.py "What content gaps exist in stoic philosophy content?"
```

## Connecting to the Research Agent

```bash
# Run research agent (saves transcripts automatically)
cd ../youtube-research-agent
python main.py "stoic philosophy for modern life" --research-only

# Feed real transcripts into knowledge base
cd ../youtube-rag-agent
python ingest.py --from-transcripts ../youtube-research-agent/output/transcripts/
```

Every research run permanently enriches the knowledge base. Run 10 niches → the agent has real knowledge about 30-50 videos to draw from.

## Key Design Decisions

**Chunking with overlap** — Transcripts split into 500-word chunks with 50-word overlap. Overlap prevents losing context at chunk boundaries.

**Similarity threshold** — Chunks below 0.2 cosine similarity are filtered. The agent gets nothing rather than irrelevant results.

**Same loop pattern** — `agent/loop.py` is structurally identical to the research agent loop. Same while loop, same tool execution, same JSON parsing. Different tools and prompts — that's all. The loop is reusable infrastructure.

**Source citation enforced** — System prompt requires every claim to cite a specific video. Confidence level is required. Prevents hallucination masquerading as insight.

## Connection to YouTube Research Agent

```
Research Agent                    Knowledge Agent
(youtube-research-agent)          (youtube-rag-agent)

Fetches live data          →      Queries accumulated knowledge
Saves transcripts          →      Indexes into ChromaDB
Runs per-session           →      Knowledge persists forever
```

See [youtube-research-agent](https://github.com/Rohishp/youtube-research-agent) for the companion project.

## Tech Stack

OpenAI API (gpt-4o, text-embedding-3-small) · ChromaDB 0.5+ · Pydantic v2
