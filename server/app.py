"""
Code Review Triage — FastAPI Server (pure FastAPI, no openenv-core at runtime)

Implements the openenv WebSocket protocol manually:
  Client sends: {"type": "reset"|"step"|"state"|"close", "data": {...}}
  Server sends: {"type": "observation"|"state"|"error", "data": {...}}

Endpoints:
  GET  /health        → liveness probe
  GET  /metadata      → environment metadata
  GET  /schema        → JSON schemas
  POST /mcp           → JSON-RPC 2.0 stub
  POST /reset         → start a new episode (HTTP)
  POST /step          → submit an action (HTTP)
  GET  /state         → episode metadata (HTTP)
  GET  /tasks         → list all task IDs with grader info
  POST /grade         → grade an action directly
  POST /tasks/{id}/grade → grade for a specific task
  WS   /ws            → WebSocket interface (openenv protocol)
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action
except ModuleNotFoundError:
    from server.environment import CodeReviewEnvironment, TASKS, TASK_ORDER, grade_action

try:
    from models import CodeReviewAction, CodeReviewObservation, CodeReviewState
except ModuleNotFoundError:
    from models import CodeReviewAction, CodeReviewObservation, CodeReviewState

app = FastAPI(
    title="Code Review Triage",
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

# HTTP session store for stateless REST usage
_sessions: dict = {}


# ── Health / Info ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "healthy"}


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
    }


@app.get("/schema")
def schema():
    return {
        "action": CodeReviewAction.model_json_schema(),
        "observation": CodeReviewObservation.model_json_schema(),
        "state": CodeReviewState.model_json_schema(),
    }


@app.post("/mcp")
async def mcp(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return {
        "jsonrpc": "2.0",
        "id": body.get("id", 1),
        "result": {
            "name": "code-review-triage",
            "version": "1.0.0",
            "capabilities": ["reset", "step", "state"],
        },
    }


# ── Task listing and grading ──────────────────────────────────────────────────

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
        return JSONResponse({"error": f"Unknown task_id '{task_id}'"}, status_code=404)
    task = TASKS[task_id]
    return {
        "task_id": task_id,
        "difficulty": task["difficulty"],
        "pr_title": task["pr_title"],
        "has_grader": True,
        "score_range": [0.0, 1.0],
        "grader_endpoint": f"/tasks/{task_id}/grade",
    }


@app.post("/grade")
async def grade(request: Request):
    body = await request.json()
    task_id = body.get("task_id", "task_easy")
    action = body.get("action", {})
    if task_id not in TASKS:
        return JSONResponse({"error": f"Unknown task_id '{task_id}'"}, status_code=404)
    score, feedback = grade_action(action, TASKS[task_id])
    return {"task_id": task_id, "score": score, "feedback": feedback, "score_range": [0.0, 1.0]}


@app.post("/tasks/{task_id}/grade")
async def grade_task(task_id: str, request: Request):
    if task_id not in TASKS:
        return JSONResponse({"error": f"Unknown task_id '{task_id}'"}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = {}
    action = body.get("action", {})
    score, feedback = grade_action(action, TASKS[task_id])
    return {"task_id": task_id, "score": score, "feedback": feedback, "score_range": [0.0, 1.0]}


# ── HTTP simulation endpoints ─────────────────────────────────────────────────

@app.post("/reset")
async def reset(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    env = CodeReviewEnvironment()
    task_id = body.get("task_id", "task_easy")
    result = env.reset(task_id=task_id, episode_id=body.get("episode_id"))
    session_key = task_id + "_http"
    _sessions[session_key] = env
    return result


@app.post("/step")
async def step(request: Request):
    body = await request.json()
    action = body.get("action", {})
    task_id = body.get("task_id", "task_easy")
    session_key = task_id + "_http"
    if session_key not in _sessions:
        env = CodeReviewEnvironment()
        env.reset(task_id=task_id)
        _sessions[session_key] = env
    return _sessions[session_key].step(action)


@app.get("/state")
def state(task_id: str = "task_easy"):
    session_key = task_id + "_http"
    if session_key not in _sessions:
        return JSONResponse({"error": "No active episode. Call /reset first."}, status_code=404)
    return _sessions[session_key].get_state()


# ── WebSocket — openenv protocol ─────────────────────────────────────────────

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
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "Invalid JSON", "code": "INVALID_JSON"},
                }))
                continue

            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "reset":
                result = env.reset(**data)
                await websocket.send_text(json.dumps({
                    "type": "observation",
                    "data": result,
                }))

            elif msg_type == "step":
                result = env.step(data)
                await websocket.send_text(json.dumps({
                    "type": "observation",
                    "data": result,
                }))

            elif msg_type == "state":
                await websocket.send_text(json.dumps({
                    "type": "state",
                    "data": env.get_state(),
                }))

            elif msg_type == "close":
                break

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {
                        "message": f"Unknown message type: '{msg_type}'",
                        "code": "UNKNOWN_TYPE",
                    },
                }))

    except WebSocketDisconnect:
        pass


def main():
    import uvicorn
    port = int(os.getenv("PORT", "7860"))
    uvicorn.run("server.app:app", host="0.0.0.0", port=port, workers=1)


if __name__ == "__main__":
    main()
