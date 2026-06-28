from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Send
from pathlib import Path
from prompts import ORCHESTRATOR_PROMPT, WORKER_PROMPT, ROUTER_PROMPT, RESEARCH_PROMPT
from typing import List
from langchain_community.tools.tavily_search import TavilySearchResults

from models import Plan, State, RouterDecision, EvidencePack, Task, EvidenceItem

from dotenv import load_dotenv
load_dotenv()

llm = ChatOpenAI(model="gpt-4.1-mini")

def router_node(state: State) -> dict:
    topic = state["topic"]

    try:
        decider = llm.with_structured_output(RouterDecision)
        decision = decider.invoke(
            [
                SystemMessage(content=ROUTER_PROMPT),
                HumanMessage(content=f"Topic: {topic}"),
            ]
        )

        return {
            "needs_research": decision.needs_research,
            "mode": decision.mode,
            "queries": decision.queries,
        }
    except Exception as e:
        raise RuntimeError(f"Router failed: {e}") from e

def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"

def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    try:
        tool = TavilySearchResults(max_results=max_results)
        results = tool.invoke({"query": query})

        normalized: List[dict] = []
        for r in results or []:
            normalized.append(
                {
                    "title": r.get("title") or "",
                    "url": r.get("url") or "",
                    "snippet": r.get("content") or r.get("snippet") or "",
                    "published_at": r.get("published_date") or r.get("published_at"),
                    "source": r.get("source"),
                }
            )
        return normalized
    except Exception as e:
        # One failing query shouldn't kill all research — skip it and continue
        return []

def research_node(state: State) -> dict:
    queries = (state.get("queries", []) or [])
    max_results = 6

    raw_results: List[dict] = []

    for q in queries:
        raw_results.extend(_tavily_search(q, max_results=max_results))

    if not raw_results:
        return {"evidence": [], "mode": "closed_book"}
    
    try:

        extractor = llm.with_structured_output(EvidencePack)
        pack = extractor.invoke(
            [
                SystemMessage(content=RESEARCH_PROMPT),
                HumanMessage(content=f"Raw results:\n{raw_results}"),
            ]
        )
        dedup = {}
        for e in pack.evidence:
            if e.url:
                dedup[e.url] = e

        return {"evidence": list(dedup.values())}
    # LLM synthesis failed — build evidence directly from raw results
    except Exception as e:
        evidence = []
        for r in raw_results:
            if r.get("url"):
                try:
                    evidence.append(EvidenceItem(
                        title=r.get("title") or "Untitled",
                        url=r["url"],
                        snippet=r.get("snippet", "")[:300],
                        published_at=r.get("published_at"),
                        source=r.get("source"),
                    ))
                except Exception:
                    pass
        dedup = {e.url: e for e in evidence}
        return {"evidence": list(dedup.values())}


def orchestrator_node(state: State) -> dict:

    evidence = state.get("evidence", [])
    mode = state.get("mode", "closed_book")

    try:
        planner = llm.with_structured_output(Plan)

        plan = planner.invoke(
            [
                SystemMessage(content=ORCHESTRATOR_PROMPT),
                HumanMessage(
                    content=(
                        f"Topic: {state['topic']}\n"
                        f"Mode: {mode}\n\n"
                        f"Evidence (ONLY use for fresh claims; may be empty):\n"
                        f"{[e.model_dump() for e in evidence][:16]}"
                    )
                ),
            ]
        )

        return {"plan": plan}
    except Exception as e:
        raise RuntimeError(f"Orchestrator failed: {e}") from e

def fanout(state: State):
    return [
        Send(
            "worker",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "plan": state["plan"].model_dump(),
                "evidence": [e.model_dump() for e in state.get("evidence", [])],
            },
        )
        for task in state["plan"].tasks
    ]

def worker_node(payload: dict) -> dict:
    
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]
    topic = payload["topic"]
    mode = payload.get("mode", "closed_book")

    bullets_text = "\n- " + "\n- ".join(task.bullets)

    evidence_text = ""
    if evidence:
        evidence_text = "\n".join(
            f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}".strip()
            for e in evidence[:20]
        )

    try:

        section_md = llm.invoke(
            [
                SystemMessage(content=WORKER_PROMPT),
                HumanMessage(
                    content=(
                        f"Blog title: {plan.blog_title}\n"
                        f"Audience: {plan.audience}\n"
                        f"Tone: {plan.tone}\n"
                        f"Blog kind: {plan.blog_kind}\n"
                        f"Constraints: {plan.constraints}\n"
                        f"Topic: {topic}\n"
                        f"Mode: {mode}\n\n"
                        f"Section title: {task.title}\n"
                        f"Goal: {task.goal}\n"
                        f"Target words: {task.target_words}\n"
                        f"Tags: {task.tags}\n"
                        f"requires_research: {task.requires_research}\n"
                        f"requires_citations: {task.requires_citations}\n"
                        f"requires_code: {task.requires_code}\n"
                        f"Bullets:{bullets_text}\n\n"
                        f"Evidence (ONLY use these URLs when citing):\n{evidence_text}\n"
                    )
                ),
            ]
        ).content.strip()
    except Exception as e:
        section_md = f"## {task.title}\n\n> ⚠️ This section could not be generated: {e}\n"

    return {"sections": [(task.id, section_md)]}


def reducer_node(state: State) -> dict:
    plan = state["plan"]

    ordered_sections = [md for _, md in sorted(state["sections"], key=lambda x: x[0])]
    body = "\n\n".join(ordered_sections).strip()
    final_md = f"# {plan.blog_title}\n\n{body}\n"

    filename = f"{plan.blog_title}.md"
    try:
        Path(filename).write_text(final_md, encoding="utf-8")
    except Exception as e:
        print(f"Warning: could not save file: {e}")

    return {"final": final_md}