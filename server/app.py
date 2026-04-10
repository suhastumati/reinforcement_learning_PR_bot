"""
Code Review Triage — FastAPI Server

Built on openenv-core's create_app() for correct WebSocket protocol.
Additional endpoints for task listing and grading are registered manually.

Endpoints:
  GET  /health          → liveness probe
  GET  /metadata        → environment metadata
  GET  /schema          → JSON schemas
  POST /reset           → start a new episode
  POST /step            → submit a review action
  GET  /state           → get episode metadata
  GET  /tasks           → list available task IDs
  POST /grade           → grade an action directly
  POST /tasks/{id}/grade → grade an action for a specific task
  WS   /ws              → WebSocket interface (openenv-core protocol)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.middleware.cors import CORSMiddleware
from openenv.core.env_server.http_server import create_app

try:
    from environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action
except ModuleNotFoundError:
    from server.environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action

try:
    from models import CodeReviewAction, CodeReviewObservation
except ModuleNotFoundError:
    from models import CodeReviewAction, CodeReviewObservation


# ─── Build app using openenv-core (handles /ws, /health, /metadata, /schema, etc.) ──

app = create_app(
    env=CodeReviewEnvironment,
    action_cls=CodeReviewAction,
    observation_cls=CodeReviewObservation,
    env_name="code-review-triage",
    max_concurrent_envs=10,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Extra endpoints for task listing and direct grading ─────────────────────

@app.get("/tasks")
def list_tasks():
    return {
        "tasks": [
            {
                "task_id": tid,
                "difficulty": TASKS[tid]["difficulty"],
                "pr_title": TASKS[tid]["pr_title"],
                "has_grader": True,
                "score_range": [0.0, 1.0],
                "grader": "grade_action",
                "grader_endpoint": f"/tasks/{tid}/grade",
            }
            for tid in TASK_ORDER
        ]
    }


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    if task_id not in TASKS:
        return {"error": f"Unknown task_id '{task_id}'. Valid: {TASK_ORDER}"}
    task = TASKS[task_id]
    return {
        "task_id": task_id,
        "difficulty": task["difficulty"],
        "pr_title": task["pr_title"],
        "grader": True,
        "score_range": [0.0, 1.0],
        "grader_endpoint": f"/tasks/{task_id}/grade",
    }


@app.post("/grade")
def grade(body: dict):
    """Directly grade an action against a task without running a full episode."""
    task_id = body.get("task_id", "task_easy")
    action = body.get("action", {})
    if task_id not in TASKS:
        return {"error": f"Unknown task_id '{task_id}'. Valid: {TASK_ORDER}"}
    score, feedback = grade_action(action, TASKS[task_id])
    return {
        "task_id": task_id,
        "score": score,
        "feedback": feedback,
        "score_range": [0.0, 1.0],
    }


@app.post("/tasks/{task_id}/grade")
def grade_task(task_id: str, body: dict = None):
    """Grade an action for a specific task (alternative path)."""
    body = body or {}
    action = body.get("action", {})
    if task_id not in TASKS:
        return {"error": f"Unknown task_id '{task_id}'. Valid: {TASK_ORDER}"}
    score, feedback = grade_action(action, TASKS[task_id])
    return {
        "task_id": task_id,
        "score": score,
        "feedback": feedback,
        "score_range": [0.0, 1.0],
    }


def main():
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()
