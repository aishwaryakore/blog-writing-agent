from pydantic import BaseModel, Field
from typing import TypedDict, Annotated, List, Literal, Optional
import operator

class Task(BaseModel):
    id: int
    title: str

    goal: str = Field(
        ...,
        description="One sentence describing what the reader should be able to do/understand after this section.",
    )
    bullets: List[str] = Field(
        ...,
        min_length=3,
        max_length=5,
        description="3–5 concrete, non-overlapping subpoints to cover in this section.",
    )
    target_words: int = Field(
        ...,
        description="Target word count for this section (120–450).",
    )
    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False

class Plan(BaseModel):
    blog_title: str
    audience: str = Field(..., description="Who this blog is for.")
    tone: str = Field(..., description="Writing tone (e.g., practical, crisp).")
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]

class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None

class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    queries: List[str] = Field(default_factory=list)

class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)

class SectionFeedback(BaseModel):
    section_title: str
    issue: str = Field(..., description="One sentence describing what is weak or wrong.")
    rewrite_instruction: str = Field(..., description="Specific instruction for the rewrite.")

class EvalResult(BaseModel):
    passed: bool = Field(..., description="True if the blog meets quality bar, False if rewrites needed.")
    overall_feedback: str = Field(..., description="1-2 sentence summary of the evaluation.")
    weak_sections: List[SectionFeedback] = Field(
        default_factory=list,
        description="List of sections that need rewriting. Empty if passed=True."
    )

class State(TypedDict):
    topic: str
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Plan
    sections: Annotated[List[str], operator.add]
    final: str
    # User configurable parameters (OPTIONAL)
    tone: Optional[str]
    audience: Optional[str]
    length: Optional[str] # short, medium or long
    # evaluation
    eval_result: Optional[EvalResult]
    eval_attempts: int 