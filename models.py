"""
Code Review Triage Environment — Typed Models

Action:   The agent's review decision (severity label + inline comments + approve/reject)
Observation: The PR diff + file context the agent sees
State:    Episode metadata (task_id, step_count, etc.)
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ─── Base classes (mirrors openenv-core interface) ────────────────────────────

class Action(BaseModel):
    pass

class Observation(BaseModel):
    done: bool = False
    reward: Optional[float] = None

class State(BaseModel):
    episode_id: Optional[str] = None
    step_count: int = 0


# ─── Domain models ────────────────────────────────────────────────────────────

class InlineComment(BaseModel):
    """A comment attached to a specific line in the diff."""
    line_number: int = Field(..., description="Line number in the diff (1-indexed)")
    comment: str = Field(..., description="The review comment text")


class CodeReviewAction(Action):
    """What the agent produces after reviewing a PR diff."""
    severity: str = Field(
        ...,
        description=(
            "Severity label for the PR. One of: "
            "'critical' (security/crash bug), "
            "'major' (logic error, bad perf), "
            "'minor' (style, nit), "
            "'approved' (looks good)"
        ),
    )
    inline_comments: List[InlineComment] = Field(
        default_factory=list,
        description="Inline review comments attached to specific diff lines",
    )
    summary: str = Field(
        ...,
        description="Overall review summary (1-3 sentences)",
    )
    approve: bool = Field(
        ...,
        description="True to approve the PR, False to request changes",
    )


class CodeReviewObservation(Observation):
    """What the agent sees: the PR diff and context."""
    task_id: str = Field(..., description="Unique identifier for this task scenario")
    task_difficulty: str = Field(..., description="'easy', 'medium', or 'hard'")
    pr_title: str = Field(..., description="Title of the pull request")
    pr_description: str = Field(..., description="PR description / author's intent")
    diff: str = Field(..., description="The unified diff of the PR")
    file_context: str = Field(
        default="",
        description="Additional file context (imports, class definition, etc.)",
    )
    feedback: str = Field(
        default="",
        description="Feedback from the environment after a step (empty on reset)",
    )
    current_score: float = Field(
        default=0.0,
        description="Running score so far this episode (0.0–1.0)",
    )
    legal_actions: List[str] = Field(
        default_factory=lambda: ["critical", "major", "minor", "approved"],
        description=(
            "Valid severity labels at this step. "
            "Always the full set; included to match OpenEnv convention."
        ),
    )


class CodeReviewState(State):
    """Episode-level metadata."""
    task_id: str = ""
    task_difficulty: str = ""
    max_steps: int = 3
    attempts_used: int = 0
