from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Send
from pathlib import Path
from prompts import ORCHESTRATOR_PROMPT, WORKER_PROMPT, ROUTER_PROMPT, RESEARCH_PROMPT, EVALUATOR_PROMPT
from typing import List
from langchain_community.tools.tavily_search import TavilySearchResults

from models import Plan, State, RouterDecision, EvidencePack, Task, EvidenceItem, EvalResult, SectionFeedback

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

    user_tone = state.get("tone")
    user_audience = state.get("audience")
    user_length = state.get("length")

    length_hint = {
        "short": "Keep the blog concise: 3–4 sections, ~800 words total.",
        "medium": "Standard length: 5–7 sections, ~1500 words total.",
        "long": "Comprehensive coverage: 7–9 sections, ~2500 words total.",
    }.get(user_length, "")

    user_prefs = ""
    if user_tone:
        user_prefs += f"- Tone: {user_tone}\n"
    if user_audience:
        user_prefs += f"- Audience: {user_audience}\n"
    if length_hint:
        user_prefs += f"- Length: {length_hint}\n"

    try:
        planner = llm.with_structured_output(Plan)

        plan = planner.invoke(
            [
                SystemMessage(content=ORCHESTRATOR_PROMPT),
                HumanMessage(content=(
                f"Topic: {state['topic']}\n"
                f"Mode: {mode}\n"
                + (f"\nUser preferences (MUST follow these):\n{user_prefs}" if user_prefs else "")
                + f"\nEvidence (ONLY use for fresh claims; may be empty):\n"
                f"{[e.model_dump() for e in evidence][:16]}"
            )),
            ]
        )
        if user_tone:
            plan.tone = user_tone
        if user_audience:
            plan.audience = user_audience
            
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
    rewrite_instruction = payload.get("rewrite_instruction")
    issue = payload.get("issue")
    bullets_text = "\n- " + "\n- ".join(task.bullets)
    evidence_text = ""

    if evidence:
        evidence_text = "\n".join(
            f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}".strip()
            for e in evidence[:20]
        )

    rewrite_context = ""
    if rewrite_instruction:
        rewrite_context = (
            f"\nREWRITE INSTRUCTION: {rewrite_instruction}\n"
            f"Previous version had this issue: {issue}\n"
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
                        f"{rewrite_context}"
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

def rewrite_fanout(state: State):
    eval_result = state["eval_result"]
    plan = state["plan"]
    task_by_title = {task.title.lower(): task for task in plan.tasks}

    sends = []
    for fb in eval_result.weak_sections:
        task = task_by_title.get(fb.section_title.lower())
        if not task:
            continue
        sends.append(Send("worker", {
            "task": task.model_dump(),
            "topic": state["topic"],
            "mode": state["mode"],
            "plan": state["plan"].model_dump(),
            "evidence": [e.model_dump() for e in state.get("evidence", [])],
            # Pass the rewrite instruction into the payload
            "rewrite_instruction": fb.rewrite_instruction,
            "issue": fb.issue,
        }))
    return sends

def evaluator_node(state: State) -> dict:
    plan = state["plan"]
    final = state["final"]
    mode = state.get("mode", "closed_book")
    attempts = state.get("eval_attempts", 0)

    if attempts >= 1:
        return {
            "eval_result": EvalResult(passed=True, overall_feedback="Max attempts reached, passing as-is."),
            "eval_attempts": attempts,
        }

    try:
        evaluator = llm.with_structured_output(EvalResult)
        result = evaluator.invoke([
            SystemMessage(content=EVALUATOR_PROMPT),
            HumanMessage(content=(
                f"Topic: {state['topic']}\n"
                f"Audience: {plan.audience}\n"
                f"Tone: {plan.tone}\n"
                f"Mode: {mode}\n\n"
                f"Blog:\n{final}"
            )),
        ])
        return {
            "eval_result": result,
            "eval_attempts": attempts + 1,
        }
    except Exception as e:
        return {
            "eval_result": EvalResult(passed=True, overall_feedback=f"Evaluation skipped: {e}"),
            "eval_attempts": attempts + 1,
        }


def route_after_eval(state: State) -> str:
    result = state.get("eval_result")
    if result and not result.passed and state.get("eval_attempts", 0) <= 1:
        return "rewrite"
    return "end"