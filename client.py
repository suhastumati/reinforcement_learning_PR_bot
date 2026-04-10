"""
Code Review Triage — Python Client

Usage:
    from client import CodeReviewEnv, CodeReviewAction, InlineComment

    with CodeReviewEnv(base_url="http://localhost:8000").sync() as env:
        result = env.reset(task_id="task_easy")
        print(result.observation.diff)

        action = CodeReviewAction(
            severity="critical",
            inline_comments=[InlineComment(line_number=4, comment="NPE: name may be None")],
            summary="display_name can be None causing AttributeError on .upper()",
            approve=False,
        )
        result = env.step(action)
        print(result.reward, result.observation.feedback)
"""

import asyncio
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import websockets
import requests

from models import (
    CodeReviewAction,
    CodeReviewObservation,
    CodeReviewState,
    InlineComment,
)


# Re-export for convenience
__all__ = ["CodeReviewEnv", "CodeReviewAction", "CodeReviewObservation", "InlineComment"]


@dataclass
class StepResult:
    observation: CodeReviewObservation
    reward: Optional[float]
    done: bool
    info: Dict[str, Any] = field(default_factory=dict)


def _parse_result(payload: Dict[str, Any]) -> StepResult:
    obs_data = payload.get("observation", {})
    obs = CodeReviewObservation(
        done=payload.get("done", False),
        reward=payload.get("reward"),
        task_id=obs_data.get("task_id", ""),
        task_difficulty=obs_data.get("task_difficulty", ""),
        pr_title=obs_data.get("pr_title", ""),
        pr_description=obs_data.get("pr_description", ""),
        diff=obs_data.get("diff", ""),
        file_context=obs_data.get("file_context", ""),
        feedback=obs_data.get("feedback", ""),
        current_score=obs_data.get("current_score", 0.0),
    )
    return StepResult(
        observation=obs,
        reward=payload.get("reward"),
        done=payload.get("done", False),
    )


class SyncCodeReviewEnv:
    """Synchronous wrapper — use inside notebooks and scripts."""

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._ws_url = self._base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws"
        self._ws = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._connect()

    def _connect(self):
        future = asyncio.run_coroutine_threadsafe(
            websockets.connect(self._ws_url), self._loop
        )
        self._ws = future.result(timeout=10)

    def _send_recv(self, msg: dict) -> dict:
        async def _io():
            await self._ws.send(json.dumps(msg))
            raw = await self._ws.recv()
            return json.loads(raw)
        future = asyncio.run_coroutine_threadsafe(_io(), self._loop)
        return future.result(timeout=30)

    def reset(self, task_id: str = "task_easy", **kwargs) -> StepResult:
        payload = self._send_recv({"method": "reset", "params": {"task_id": task_id}})
        return _parse_result(payload)

    def step(self, action: CodeReviewAction) -> StepResult:
        payload = self._send_recv({
            "method": "step",
            "action": action.model_dump(),
        })
        return _parse_result(payload)

    def state(self) -> CodeReviewState:
        payload = self._send_recv({"method": "state"})
        return CodeReviewState(
            episode_id=payload.get("episode_id"),
            step_count=payload.get("step_count", 0),
            task_id=payload.get("task_id", ""),
            task_difficulty=payload.get("task_difficulty", ""),
            max_steps=payload.get("max_steps", 3),
            attempts_used=payload.get("attempts_used", 0),
        )

    def close(self):
        if self._ws:
            asyncio.run_coroutine_threadsafe(self._ws.close(), self._loop)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # HTTP fallback (no WebSocket needed)
    def reset_http(self, task_id: str = "task_easy") -> StepResult:
        resp = requests.post(f"{self._base_url}/reset", json={"task_id": task_id})
        resp.raise_for_status()
        return _parse_result(resp.json())

    def step_http(self, action: CodeReviewAction, task_id: str = "task_easy") -> StepResult:
        resp = requests.post(
            f"{self._base_url}/step",
            json={"action": action.model_dump(), "task_id": task_id},
        )
        resp.raise_for_status()
        return _parse_result(resp.json())


class CodeReviewEnv:
    """
    Code Review Triage environment client.

    env = CodeReviewEnv(base_url="http://localhost:8000")
    with env.sync() as e:
        result = e.reset(task_id="task_easy")
    """

    def __init__(self, base_url: str):
        self._base_url = base_url

    def sync(self) -> SyncCodeReviewEnv:
        return SyncCodeReviewEnv(self._base_url)
