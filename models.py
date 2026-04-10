"""
Code Review Triage Environment — Typed Models
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class InlineComment(BaseModel):
    line_number: int = Field(..., description="Line number in the diff (1-indexed)")
    comment: str = Field(..., description="The review comment text")


class CodeReviewAction(BaseModel):
    severity: str = Field(..., description="critical | major | minor | approved")
    inline_comments: List[Dict[str, Any]] = Field(default_factory=list)
    summary: str = Field(..., description="Overall review summary")
    approve: bool = Field(..., description="True to approve, False to request changes")


class CodeReviewObservation(BaseModel):
    task_id: str
    task_difficulty: str
    pr_title: str
    pr_description: str
    diff: str
    file_context: str = ""
    feedback: str = ""
    current_score: float = 0.0
    legal_actions: List[str] = Field(default_factory=lambda: ["critical", "major", "minor", "approved"])
    done: bool = False
    reward: Optional[float] = None


class CodeReviewState(BaseModel):
    episode_id: Optional[str] = None
    step_count: int = 0
    task_id: str = ""
    task_difficulty: str = ""
    max_steps: int = 3
    attempts_used: int = 0
    best_score: float = 0.0
