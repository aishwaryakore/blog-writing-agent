from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.types import Send
from pathlib import Path

from models import Plan, State

llm = ChatOpenAI(model="gpt-4.1-mini")

def orchestrator(state: State) -> dict:
    plan = llm.with_structured_output(Plan).invoke(
        [
            SystemMessage(content="Create a blog plan with 5-7 sections on the following topic."),
            HumanMessage(content=f"Topic: {state['topic']}")
        ]
    )
    return {"plan": plan}

def fanout(state: State):
    return [
        Send("worker", {"task": task, "topic": state["topic"], "plan": state["plan"]})
        for task in state["plan"].tasks
    ]

def worker(payload: dict) -> dict:
    task = payload["task"]
    topic = payload["topic"]
    plan = payload["plan"]

    section_markdown = llm.invoke(
        [
            SystemMessage(content="Write one clean Markdown section."),
            HumanMessage(content=(
                f"Blog: {plan.blog_title}\n"
                f"Topic: {topic}\n\n"
                f"Section: {task.title}\n"
                f"Brief: {task.brief}\n\n"
                "Return only the section content in Markdown."
            ))
        ]
    ).content.strip()

    return {"sections": [section_markdown]}

def reducer(state: State) -> dict:
    title = state["plan"].blog_title
    body = "\n\n".join(state["sections"]).strip()

    final_md = f"# {title}\n\n{body}\n"

    filename = title.lower().replace(" ", "_") + ".md"
    Path(filename).write_text(final_md, encoding="utf-8")

    return {"final": final_md}