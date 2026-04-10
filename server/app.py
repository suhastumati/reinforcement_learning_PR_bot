"""
Code Review Triage — FastAPI Server

Endpoints:
  GET  /health          → liveness probe
  POST /reset           → start a new episode
  POST /step            → submit a review action
  GET  /state           → get episode metadata
  GET  /tasks           → list available task IDs
  WS   /ws              → WebSocket interface (reset / step / state)
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

try:
    from environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action
except ModuleNotFoundError:
    from server.environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action

try:
    from models import CodeReviewAction, CodeReviewObservation, CodeReviewState
except ModuleNotFoundError:
    from models import CodeReviewAction, CodeReviewObservation, CodeReviewState

app = FastAPI(
    title="Code Review Triage Environment",
    description=(
        "An OpenEnv-compatible RL environment where agents learn to triage "
        "pull request diffs: detect bugs, security issues, and architecture problems."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Session store (one env per WebSocket connection) ────────────────────────

_sessions: dict = {}


# ─── HTTP endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "healthy", "environment": "code-review-triage"}


@app.get("/metadata")
def metadata():
    return {
        "name": "code-review-triage",
        "description": (
            "An RL environment where an agent learns to triage pull request diffs: "
            "detect bugs, security vulnerabilities, and architectural problems, "
            "producing structured reviews with severity labels and inline comments."
        ),
        "version": "1.0.0",
        "author": "Suhas Pranay",
        "tags": ["openenv", "code-review", "security", "nlp", "real-world"],
    }


@app.get("/schema")
def schema():
    return {
        "action": CodeReviewAction.model_json_schema(),
        "observation": CodeReviewObservation.model_json_schema(),
        "state": CodeReviewState.model_json_schema(),
    }


@app.post("/mcp")
async def mcp(request: dict = None):
    request = request or {}
    return {
        "jsonrpc": "2.0",
        "id": request.get("id", 1),
        "result": {
            "name": "code-review-triage",
            "version": "1.0.0",
            "capabilities": ["reset", "step", "state"],
        },
    }


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
            }
            for tid in TASK_ORDER
        ]
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


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    """Get details for a specific task including grader info."""
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


@app.post("/reset")
def reset(body: dict = None):
    body = body or {}
    env = CodeReviewEnvironment()
    task_id = body.get("task_id", "task_easy")
    obs = env.reset(task_id=task_id, episode_id=body.get("episode_id"))
    # Store under episode_id for stateless HTTP usage
    episode_id = obs["observation"]["task_id"] + "_http"
    _sessions[episode_id] = env
    return obs


@app.post("/step")
def step(body: dict):
    # Stateless HTTP: reconstruct env from task_id if needed
    # For production use WebSocket sessions
    action = body.get("action", {})
    task_id = body.get("task_id", "task_easy")
    session_key = task_id + "_http"
    if session_key not in _sessions:
        env = CodeReviewEnvironment()
        env.reset(task_id=task_id)
        _sessions[session_key] = env
    env = _sessions[session_key]
    return env.step(action)


@app.get("/state")
def state(task_id: str = "task_easy"):
    session_key = task_id + "_http"
    if session_key not in _sessions:
        return {"error": "No active episode. Call /reset first."}
    return _sessions[session_key].state()


# ─── WebSocket endpoint ──────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    env = CodeReviewEnvironment()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"error": "Invalid JSON"}))
                continue

            method = msg.get("method", "")

            if method == "reset":
                params = msg.get("params", {})
                result = env.reset(**params)
                await websocket.send_text(json.dumps(result))

            elif method == "step":
                action = msg.get("action", {})
                result = env.step(action)
                await websocket.send_text(json.dumps(result))

            elif method == "state":
                await websocket.send_text(json.dumps(env.state()))

            else:
                await websocket.send_text(
                    json.dumps({"error": f"Unknown method '{method}'. Use reset/step/state."})
                )

    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()
