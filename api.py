from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from workflow import create_workflow

app = FastAPI(title="Blog Writing Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

workflow = create_workflow()

class GenerateRequest(BaseModel):
    topic: str
    tone: Optional[str] = None
    audience: Optional[str] = None
    length: Optional[str] = None

def get_initial_state(topic: str, tone=None, audience=None, length=None) -> dict:
    return {
        "topic": topic,
        "mode": "",
        "needs_research": False,
        "queries": [],
        "evidence": [],
        "plan": None,
        "sections": [],
        "final": "",
        "tone": tone,
        "audience": audience,
        "length": length,
        "eval_result": None,
        "eval_attempts": 0,
    }

NODE_LABELS = {
    "router":       "🔍 Analyzing topic and deciding research strategy...",
    "research":     "🌐 Searching the web for up-to-date sources...",
    "orchestrator": "🗂️  Planning blog structure and sections...",
    "worker":       "✍️  Writing sections in parallel...",
    "reducer":      "📝 Assembling final blog post...",
    "evaluator":    "🔎 Evaluating blog quality...",
}

async def stream_blog(topic: str, tone=None, audience=None, length=None):
    initial_state = get_initial_state(topic, tone, audience, length)
    seen_nodes = set()
    done_sent = False 

    try:
        for step in workflow.stream(initial_state):
            for name, update in step.items():

                if name not in seen_nodes:
                    seen_nodes.add(name)
                    label = NODE_LABELS.get(name, f"Running {name}...")
                    yield {
                        "event": "progress",
                        "data": json.dumps({"node": name, "message": label}),
                    }

                if name == "router" and isinstance(update, dict):
                    mode = update.get("mode", "")
                    needs_research = update.get("needs_research", False)
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "node": "router_result",
                            "message": f"Mode: {mode} | Research needed: {needs_research}",
                        }),
                    }

                if name == "orchestrator" and isinstance(update, dict):
                    plan = update.get("plan")
                    if plan:
                        plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else plan
                        title = plan_dict.get("blog_title", "")
                        num_sections = len(plan_dict.get("tasks", []))
                        yield {
                            "event": "progress",
                            "data": json.dumps({
                                "node": "plan_ready",
                                "message": f"📋 Plan ready: '{title}' — {num_sections} sections to write",
                            }),
                        }

                if name == "evaluator" and isinstance(update, dict):
                    result = update.get("eval_result")
                    if result:
                        if result.passed:
                            status = "✅ Quality check passed!"
                        else:
                            status = f"⚠️ Rewriting {len(result.weak_sections)} weak section(s)..."
                        yield {
                            "event": "progress",
                            "data": json.dumps({"node": "eval_result", "message": status}),
                        }

                if name == "reducer" and isinstance(update, dict):
                    final_blog = update.get("final", "")
                    if final_blog:
                        done_sent = True
                        yield {
                            "event": "done",
                            "data": json.dumps({"blog": final_blog}),
                        }

        if not done_sent:
            yield {
                "event": "error",
                "data": json.dumps({"message": "Pipeline completed but no output was produced."}),
            }

    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"message": f"Pipeline error: {str(e)}"}),
        }


@app.post("/generate")
async def generate(request: GenerateRequest):
    return EventSourceResponse(stream_blog(request.topic, request.tone, request.audience, request.length))


@app.get("/health")
async def health():
    return {"status": "ok"}