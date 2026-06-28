from dotenv import load_dotenv
from workflow import create_workflow

load_dotenv()

if __name__ == "__main__":
    workflow = create_workflow()

    result = workflow.invoke({
            "topic": "State of Multimodal LLMs in 2026",
            "mode": "",
            "needs_research": False,
            "queries": [],
            "evidence": [],
            "plan": None,
            "sections": [],
            "final": "",
        })

    print(result["final"])