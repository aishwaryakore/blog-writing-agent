from dotenv import load_dotenv
from workflow import create_workflow

load_dotenv()

if __name__ == "__main__":
    workflow = create_workflow()

    result = workflow.invoke({
        "topic": "Write a blog on Self Attention",
        "sections": []
    })

    print(result["final"])