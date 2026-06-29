# Blog Writing Agent

An agentic AI pipeline that turns a topic into a complete, well-structured technical blog post. Built with LangGraph for multi-step orchestration, it researches the web when needed, plans the structure, writes sections in parallel, and self-evaluates the output before returning it.

---

## Architecture

```
START → router → [research] → orchestrator → workers (parallel) → reducer → evaluator → END
                                                                                 ↓
                                                  rewrite weak sections → workers → reducer
```

**Router** — classifies the topic into one of three modes:
- `closed_book` — evergreen topic, no research needed (e.g. "how transformers work")
- `hybrid` — mostly evergreen but benefits from current examples (e.g. "best vector databases")
- `open_book` — volatile/current topic, full web research required (e.g. "state of AI agents in 2026")

**Research** — runs Tavily web searches across multiple queries, synthesizes results into structured evidence items with source URLs and dates.

**Orchestrator** — produces a full structured blog plan: title, audience, tone, blog kind, and 5–9 sections each with a goal, bullets, word target, and flags for code/citations.

**Workers** — one worker per section, all running in parallel via LangGraph's `Send` API. Each worker writes its section in Markdown, grounded in the evidence.

**Reducer** — sorts and assembles all sections into the final Markdown document and saves it to disk.

**Evaluator** — scores the assembled blog on coverage, tone/audience fit, section quality, and citation discipline. If sections fail, they are sent back to the worker for a targeted rewrite with specific instructions. Maximum one rewrite cycle.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph |
| LLM framework | LangChain |
| Language model | OpenAI gpt-4.1-mini |
| Web research | Tavily Search API |
| Backend API | FastAPI + SSE streaming |
| Observability | LangSmith |
| Data validation | Pydantic v2 |

---

## Features

- **Conditional research routing** — automatically decides whether and how much web research a topic needs
- **Parallel section writing** — all blog sections are written concurrently, not sequentially
- **Structured outputs at every stage** — router, orchestrator, research synthesizer, and evaluator all use Pydantic-validated structured LLM outputs
- **Self-evaluation with targeted rewrites** — an evaluator node scores the blog and rewrites only the weak sections, not the whole thing
- **Streaming API** — FastAPI endpoint streams live progress events (SSE) as each pipeline stage completes
- **User-configurable parameters** — optional `tone`, `audience`, and `length` parameters that flow through the entire pipeline
- **Citation discipline** — workers are strictly forbidden from fabricating URLs; unsourced claims are flagged visibly in the output
- **Graceful degradation** — Tavily failures fall back per-query, research failures fall back to raw results, worker failures insert visible placeholders

---

## Project Structure

```
blog-writing-agent/
├── api.py          # FastAPI app with SSE streaming endpoint
├── workflow.py     # LangGraph graph definition
├── nodes.py        # All node functions (router, research, orchestrator, worker, reducer, evaluator)
├── models.py       # Pydantic models for state and structured outputs
├── prompts.py      # System prompts for each LLM-powered node
├── main.py         # CLI entry point for quick local testing
└── .env            # API keys (see setup)
```

---

## Setup

**1. Clone and create a virtual environment**
```bash
git clone https://github.com/your-username/blog-writing-agent.git
cd blog-writing-agent
python3 -m venv bwa-venv
source bwa-venv/bin/activate
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set up environment variables**

Create a `.env` file in the project root:
```
OPENAI_API_KEY=your_openai_key
TAVILY_API_KEY=your_tavily_key

# Optional: enables LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=blog-writing-agent
```

**4. Run the API**
```bash
python -m uvicorn api:app --reload --port 8000
```

---

## Usage

**Basic request:**
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"topic": "How does RAG work"}' \
  --no-buffer
```

**With optional parameters:**
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "How does RAG work",
    "tone": "casual and beginner-friendly",
    "audience": "junior developers",
    "length": "short"
  }' \
  --no-buffer
```

**Optional parameters:**

| Parameter | Values | Description |
|---|---|---|
| `tone` | any string | e.g. "casual", "formal", "beginner-friendly" |
| `audience` | any string | e.g. "junior developers", "ML engineers" |
| `length` | `short`, `medium`, `long` | ~800 / ~1500 / ~2500 words |

**SSE event types:**

| Event | Payload | Description |
|---|---|---|
| `progress` | `{ node, message }` | Live pipeline stage update |
| `done` | `{ blog }` | Final Markdown blog post |
| `error` | `{ message }` | Something went wrong |

**Example stream output:**
```
event: progress
data: {"node": "router", "message": "Analyzing topic and deciding research strategy..."}

event: progress
data: {"node": "router_result", "message": "Mode: closed_book | Research needed: False"}

event: progress
data: {"node": "orchestrator", "message": "Planning blog structure and sections..."}

event: progress
data: {"node": "plan_ready", "message": "Plan ready: 'How RAG Works' — 6 sections to write"}

event: progress
data: {"node": "worker", "message": "Writing sections in parallel..."}

event: progress
data: {"node": "reducer", "message": "Assembling final blog post..."}

event: progress
data: {"node": "evaluator", "message": "Evaluating blog quality..."}

event: progress
data: {"node": "eval_result", "message": "Quality check passed!"}

event: done
data: {"blog": "# How RAG Works\n\n## Introduction\n..."}
```

**Health check:**
```bash
curl http://localhost:8000/health
```

**Interactive API docs** (auto-generated by FastAPI):
```
http://localhost:8000/docs
```

---

## Key Design Decisions

**Why LangGraph over a simple chain?**
The pipeline has conditional branching (research or not), parallel fan-out (one worker per section), and a feedback loop (evaluator → rewrite). These patterns require a proper graph, not a linear chain.

**Why parallel workers?**
A 7-section blog with sequential writing would take 7x longer. LangGraph's `Send` API lets all sections be written concurrently, cutting generation time significantly.

**Why a separate evaluator node?**
LLMs can produce sections that are vague, off-tone, or poorly structured even with good prompts. A dedicated evaluator node with a strict rubric catches these issues and rewrites only the failing sections — not the whole blog — keeping cost and latency low.

**Why SSE over WebSockets?**
Blog generation takes 30–90 seconds. SSE lets the client show live progress without a blank screen, using standard HTTP with no extra protocol overhead. It's one-way (server → client) which is all we need here.