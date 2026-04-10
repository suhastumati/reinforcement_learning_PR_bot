"""
Code Review Triage — Baseline Inference Script

Required environment variables:
  API_BASE_URL   LLM API base URL       (default: https://router.huggingface.co/v1)
  MODEL_NAME     Model identifier       (default: Qwen/Qwen2.5-72B-Instruct)
  HF_TOKEN       Hugging Face API key   (required, no default)

Log format (stdout):
  [START] task=<task> env=<env> model=<model>
  [STEP]  step=<n> action=<single-line-json> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<0.00> rewards=<r1,r2,...>

Run:
  export HF_TOKEN=hf_...
  export SERVER_URL=http://localhost:7860
  python inference.py
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

import requests
from openai import OpenAI

# ─── Configuration ────────────────────────────────────────────────────────────

API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
HF_TOKEN: Optional[str] = os.getenv("HF_TOKEN")

SERVER_URL: str = os.getenv("SERVER_URL", "http://localhost:7860")

TASKS = ["task_easy", "task_medium", "task_hard"]
MAX_STEPS = 3
MAX_TOKENS = 1024
SUCCESS_SCORE_THRESHOLD = 0.7
BENCHMARK = "code-review-triage"


# ─── Structured log helpers (exact required format) ──────────────────────────

def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(
    step: int,
    action: Any,
    reward: float,
    done: bool,
    error: Optional[str],
) -> None:
    # Emit action as compact single-line JSON (no spaces after separators)
    try:
        action_str = json.dumps(action, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        action_str = str(action)
    if len(action_str) > 200:
        action_str = action_str[:200] + "..."
    done_str = "true" if done else "false"
    error_str = error if error is not None else "null"
    print(
        f"[STEP] step={step} action={action_str} reward={reward:.2f} done={done_str} error={error_str}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    success_str = "true" if success else "false"
    rewards_str = ",".join(f"{r:.2f}" for r in rewards) if rewards else ""
    print(
        f"[END] success={success_str} steps={steps} score={score:.2f} rewards={rewards_str}",
        flush=True,
    )


# ─── Environment HTTP helpers ─────────────────────────────────────────────────

def env_reset(task_id: str) -> Dict[str, Any]:
    resp = requests.post(f"{SERVER_URL}/reset", json={"task_id": task_id}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def env_step(action: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    resp = requests.post(
        f"{SERVER_URL}/step",
        json={"action": action, "task_id": task_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ─── LLM call ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert software engineer performing code review.

When given a pull request diff, output a structured JSON code review with exactly these fields:
{
  "severity": "<one of: critical, major, minor, approved>",
  "inline_comments": [
    {"line_number": <int>, "comment": "<specific issue on this line>"}
  ],
  "summary": "<1-3 sentence overall assessment>",
  "approve": <true if PR should merge as-is, false if changes required>
}

Guidelines:
- "critical": security vulnerabilities, null/crash bugs, data loss risk
- "major": logic errors, significant performance problems, missing error handling
- "minor": style issues, minor inefficiencies, nit-picks
- "approved": code is correct and ready to merge
- Always set approve=false if severity is critical or major
- Line numbers are 1-indexed from the first line of the diff shown
- Your response must be valid JSON only — no markdown, no explanation outside JSON
"""


def get_model_action(
    client: OpenAI,
    obs: Dict[str, Any],
    feedback: str,
) -> Dict[str, Any]:
    """Call the LLM and parse its JSON review output."""
    user_content = (
        f"## Pull Request: {obs['pr_title']}\n\n"
        f"**Description:** {obs['pr_description']}\n\n"
        f"**File context:**\n```\n{obs['file_context']}\n```\n\n"
        f"**Diff:**\n```diff\n{obs['diff']}\n```\n"
    )
    if feedback:
        user_content += (
            f"\n**Previous review feedback (improve on this):** {feedback}\n"
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=0,
            stream=False,
        )
        text = (completion.choices[0].message.content or "").strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            inner = lines[1:] if lines[0].startswith("```") else lines
            text = "\n".join(inner[:-1] if inner[-1].strip() == "```" else inner)
        return json.loads(text)
    except (json.JSONDecodeError, Exception):
        return {
            "severity": "minor",
            "inline_comments": [],
            "summary": "Unable to complete review.",
            "approve": True,
        }


# ─── Single task run ─────────────────────────────────────────────────────────

def run_task(client: OpenAI, task_id: str) -> Dict[str, Any]:
    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False
    last_error: Optional[str] = None

    try:
        result = env_reset(task_id)
        obs = result.get("observation", {})
        done = result.get("done", False)
        last_feedback = ""

        for step in range(1, MAX_STEPS + 1):
            if done:
                break

            action = get_model_action(client, obs, last_feedback)
            last_error = None

            try:
                step_result = env_step(action, task_id)
            except Exception as e:
                last_error = str(e)
                log_step(step=step, action=action, reward=0.0, done=True, error=last_error)
                break

            new_obs = step_result.get("observation", {})
            reward = float(step_result.get("reward") or 0.0)
            done = bool(step_result.get("done", False))

            rewards.append(reward)
            steps_taken = step
            last_feedback = new_obs.get("feedback", "")
            obs = new_obs

            log_step(step=step, action=action, reward=reward, done=done, error=None)

            if done:
                break

        score = rewards[-1] if rewards else 0.0
        score = min(max(score, 0.0), 1.0)
        success = score >= SUCCESS_SCORE_THRESHOLD

    except Exception as e:
        last_error = str(e)
        log_step(step=steps_taken + 1, action={}, reward=0.0, done=True, error=last_error)

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return {"task_id": task_id, "score": score, "success": success}


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    if HF_TOKEN is None:
        raise ValueError("HF_TOKEN environment variable is required")

    # Verify server is reachable
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Server not reachable at {SERVER_URL}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN)

    log_start(task=",".join(TASKS), env=BENCHMARK, model=MODEL_NAME)

    all_results = []
    for task_id in TASKS:
        result = run_task(client, task_id)
        all_results.append(result)
        time.sleep(0.5)

    # Print summary to stderr so it doesn't pollute the structured stdout
    total = sum(r["score"] for r in all_results)
    avg = total / len(all_results)
    print(f"[DEBUG] avg_score={avg:.3f}", file=sys.stderr)


if __name__ == "__main__":
    main()
