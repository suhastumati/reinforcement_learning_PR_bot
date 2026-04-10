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
    from environment import CodeReviewEnvironment, TASKS, TASK_ORDER
except ModuleNotFoundError:
    from server.environment import CodeReviewEnvironment, TASKS, TASK_ORDER

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


@app.get("/tasks")
def list_tasks():
    return {
        "tasks": [
            {
                "task_id": tid,
                "difficulty": TASKS[tid]["difficulty"],
                "pr_title": TASKS[tid]["pr_title"],
            }
            for tid in TASK_ORDER
        ]
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
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, workers=1)


if __name__ == "__main__":
    main()
