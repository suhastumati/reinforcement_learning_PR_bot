"""
Code Review Triage — Server-side Environment Logic

Three tasks with graders:
  Task 1 (easy):   Detect an obvious null-pointer dereference bug
  Task 2 (medium): Identify a SQL injection security vulnerability
  Task 3 (hard):   Evaluate a poorly architected async function with multiple issues
                   (race condition + missing error handling + inefficient N+1 query)
"""

import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Task definitions ─────────────────────────────────────────────────────────

TASKS: Dict[str, Dict[str, Any]] = {
    "task_easy": {
        "difficulty": "easy",
        "pr_title": "Add user greeting to dashboard",
        "pr_description": (
            "This PR adds a personalised greeting when a user logs in. "
            "The greeting uses the user's display name."
        ),
        "file_context": (
            "# user_service.py\n"
            "class User:\n"
            "    def __init__(self, username: str, display_name: Optional[str]):\n"
            "        self.username = username\n"
            "        self.display_name = display_name  # May be None for legacy accounts\n"
        ),
        "diff": (
            "@@ -0,0 +1,12 @@\n"
            "+def greet_user(user):\n"
            "+    \"\"\"Return a greeting string for the dashboard.\"\"\"\n"
            "+    name = user.display_name\n"
            "+    greeting = f\"Welcome back, {name.upper()}!\"\n"
            "+    return greeting\n"
            "+\n"
            "+def render_dashboard(user):\n"
            "+    greeting = greet_user(user)\n"
            "+    return {\"greeting\": greeting, \"tiles\": load_tiles(user)}\n"
        ),
        # Ground truth for grading
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["none", "null"],                          # null-safety issue
            ["attributeerror", "attribute error"],     # the exception type
            ["display_name"],                          # the specific field
            ["upper"],                                 # the crashing call
            ["optional", "can be none", "may be none"],# type annotation awareness
        ],
        "expected_comment_lines": [4],  # line with name.upper()
    },

    "task_medium": {
        "difficulty": "medium",
        "pr_title": "Add user search endpoint",
        "pr_description": (
            "Adds a REST endpoint to search users by username. "
            "Uses raw SQL for performance."
        ),
        "file_context": (
            "# routes/users.py\n"
            "from flask import request, jsonify\n"
            "import db  # db.execute(sql) -> list[dict]\n"
        ),
        "diff": (
            "@@ -0,0 +1,14 @@\n"
            "+@app.route('/api/users/search')\n"
            "+def search_users():\n"
            "+    query = request.args.get('q', '')\n"
            "+    sql = f\"SELECT id, username, email FROM users \"\n"
            "+          f\"WHERE username LIKE '%{query}%'\"\n"
            "+    results = db.execute(sql)\n"
            "+    return jsonify(results)\n"
            "+\n"
            "+@app.route('/api/users/<int:user_id>')\n"
            "+def get_user(user_id):\n"
            "+    sql = f\"SELECT * FROM users WHERE id = {user_id}\"\n"
            "+    row = db.execute(sql)\n"
            "+    return jsonify(row[0] if row else {})\n"
        ),
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["sql injection", "sqli"],                        # core vulnerability name
            ["parameterized", "parameterise", "parameterize", "prepared statement"],  # fix technique
            ["sanitize", "sanitise", "escape", "validate"],  # input handling
            ["f-string", "format string", "string interpolation"],  # root cause
            ["user input", "untrusted", "request.args"],     # source of taint
        ],
        "expected_comment_lines": [4, 5, 10, 11],
    },

    "task_hard": {
        "difficulty": "hard",
        "pr_title": "Async batch notification sender",
        "pr_description": (
            "Implements an async function that fetches all active users and "
            "sends each a push notification. Replaces the old synchronous version."
        ),
        "file_context": (
            "# notifications.py\n"
            "import asyncio\n"
            "import aiohttp\n"
            "from db import get_db  # async context manager\n"
            "from models import User\n"
            "PUSH_API = 'https://push.internal/send'\n"
        ),
        "diff": (
            "@@ -0,0 +1,28 @@\n"
            "+async def send_all_notifications(message: str):\n"
            "+    db = await get_db()\n"
            "+    users = await db.fetch_all('SELECT id FROM users WHERE active = 1')\n"
            "+    results = []\n"
            "+    for user in users:  # N+1: one HTTP call per user\n"
            "+        user_data = await db.fetch_one(\n"
            "+            f'SELECT * FROM users WHERE id = {user[\"id\"]}'\n"
            "+        )\n"
            "+        payload = {\n"
            "+            'user_id': user_data['id'],\n"
            "+            'token': user_data['push_token'],\n"
            "+            'message': message\n"
            "+        }\n"
            "+        async with aiohttp.ClientSession() as session:\n"
            "+            resp = await session.post(PUSH_API, json=payload)\n"
            "+            results.append(resp.status)\n"
            "+    shared_state = []\n"
            "+    async def collect(r):\n"
            "+        shared_state.append(r)  # race condition on shared list\n"
            "+    await asyncio.gather(*[collect(r) for r in results])\n"
            "+    return shared_state\n"
            "+\n"
            "+async def notify_single(user_id: int, message: str):\n"
            "+    db = await get_db()\n"
            "+    user = await db.fetch_one(f'SELECT * FROM users WHERE id = {user_id}')\n"
            "+    async with aiohttp.ClientSession() as session:\n"
            "+        await session.post(PUSH_API, json={'token': user['push_token'],\n"
            "+                                           'message': message})\n"
        ),
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["n+1", "n plus 1", "per-user query", "query per user"],  # N+1 pattern
            ["batch", "bulk", "fetch_all", "single query"],            # correct fix
            ["race condition", "race", "shared_state", "concurrent write"],  # concurrency
            ["sql injection", "sqli", "f-string", "parameterized"],   # SQLi
            ["error handling", "exception", "try", "except"],         # missing try/except
            ["clientsession", "session per", "reuse session", "aiohttp.ClientSession"],  # perf
        ],
        "expected_comment_lines": [5, 6, 7, 14, 17, 18, 19, 25],
    },
}

TASK_ORDER = ["task_easy", "task_medium", "task_hard"]


# ─── Grader ───────────────────────────────────────────────────────────────────

def _keywords_hit(text: str, keyword_groups: list) -> float:
    """
    Fraction of keyword groups matched in lowercased text.
    Each group is a list of synonyms — a group is matched if ANY synonym is found.
    """
    text_lower = text.lower()
    hits = sum(
        1 for group in keyword_groups
        if any(kw in text_lower for kw in (group if isinstance(group, list) else [group]))
    )
    return hits / max(len(keyword_groups), 1)


def grade_action(action_dict: Dict[str, Any], task: Dict[str, Any]) -> Tuple[float, str]:
    """
    Grade a CodeReviewAction against ground truth.

    Returns (score: float 0.0–1.0, feedback: str)

    Scoring breakdown:
      30%  Severity label correct
      20%  Approve/reject decision correct
      30%  Key issues mentioned in summary + comments (partial credit)
      20%  Inline comment(s) on the right line(s)

    Penalties applied before returning:
      -0.20  Approved a PR that contains a critical/major issue (exploit guard)
      -0.05  Per step taken (action cost — discourages padding)
    """
    severity_score = 0.0
    approve_score = 0.0
    issue_score = 0.0
    line_score = 0.0
    feedback_parts = []

    severity = action_dict.get("severity", "").lower().strip()
    approve = action_dict.get("approve", True)
    summary = action_dict.get("summary", "")
    inline_comments = action_dict.get("inline_comments", [])
    all_comment_text = summary + " " + " ".join(
        c.get("comment", "") for c in inline_comments
    )

    # 1. Severity (30%)
    if severity == task["expected_severity"]:
        severity_score = 1.0
        feedback_parts.append("Severity label correct.")
    elif severity in ("major", "critical") and task["expected_severity"] in ("major", "critical"):
        severity_score = 0.5
        feedback_parts.append(f"Severity close but expected '{task['expected_severity']}'.")
    else:
        feedback_parts.append(f"Wrong severity — expected '{task['expected_severity']}', got '{severity}'.")

    # 2. Approve/reject (20%)
    if approve == task["expected_approve"]:
        approve_score = 1.0
        feedback_parts.append("Approve decision correct.")
    else:
        decision = "approve" if task["expected_approve"] else "request changes"
        feedback_parts.append(f"Wrong decision — should {decision}.")

    # 3. Key issues detected (30%) — partial credit
    issue_score = _keywords_hit(all_comment_text, task["key_issues"])
    pct = int(issue_score * 100)
    feedback_parts.append(f"Key issues detected: {pct}%.")

    # 4. Inline comment line coverage (20%)
    expected_lines = set(task["expected_comment_lines"])
    commented_lines = set(c.get("line_number", -1) for c in inline_comments)
    if expected_lines:
        line_score = len(expected_lines & commented_lines) / len(expected_lines)
    feedback_parts.append(
        f"Line coverage: {int(line_score * 100)}% of key lines commented."
    )

    total = (
        0.30 * severity_score
        + 0.20 * approve_score
        + 0.30 * issue_score
        + 0.20 * line_score
    )

    # Exploit guard: penalise approving a PR with a critical/major bug
    if approve and task["expected_severity"] in ("critical", "major"):
        total -= 0.20
        feedback_parts.append("Penalty: approved a PR with critical/major issues.")

    total = round(max(0.0, min(1.0, total)), 4)
    return total, " | ".join(feedback_parts)


# ─── Dense per-step reward breakdown ─────────────────────────────────────────

def _dense_reward(
    action_dict: Dict[str, Any],
    task: Dict[str, Any],
    already_found_issues: Set[str],
    already_hit_lines: Set[int],
    step_count: int,
) -> Tuple[float, Set[str], Set[int], str]:
    """
    Compute a dense step-level reward signal.

    Rewards:
      +0.10  First time the correct severity is identified
      +0.05  First time the correct approve/reject is set
      +0.04  Per new key issue keyword discovered (first mention only)
      +0.03  Per new ground-truth diff line commented (first hit only)
    Penalties:
      -0.20  Approving a PR with a known critical/major bug
      -0.005 Action cost per step (discourages padding)
      -0.02  Per duplicate comment on the same line within the episode

    Returns (step_reward, updated_found_issues, updated_hit_lines, feedback)
    """
    step_reward = 0.0
    feedback_parts: List[str] = []

    severity = action_dict.get("severity", "").lower().strip()
    approve = action_dict.get("approve", True)
    summary = action_dict.get("summary", "")
    inline_comments = action_dict.get("inline_comments", [])
    all_text = (summary + " " + " ".join(c.get("comment", "") for c in inline_comments)).lower()

    # Severity first-discovery
    if severity == task["expected_severity"] and "_severity" not in already_found_issues:
        step_reward += 0.10
        already_found_issues = already_found_issues | {"_severity"}
        feedback_parts.append("+0.10 severity correct (first time).")
    elif severity in ("major", "critical") and task["expected_severity"] in ("major", "critical") \
            and "_severity_partial" not in already_found_issues:
        step_reward += 0.05
        already_found_issues = already_found_issues | {"_severity_partial"}
        feedback_parts.append("+0.05 severity close (first time).")

    # Approve/reject first-discovery
    if approve == task["expected_approve"] and "_approve" not in already_found_issues:
        step_reward += 0.05
        already_found_issues = already_found_issues | {"_approve"}
        feedback_parts.append("+0.05 approve decision correct (first time).")

    # Key issues — credit first group matched only (OR-group format)
    for group in task["key_issues"]:
        synonyms = group if isinstance(group, list) else [group]
        group_key = synonyms[0]  # canonical name for tracking
        matched = any(kw in all_text for kw in synonyms)
        if matched and group_key not in already_found_issues:
            step_reward += 0.04
            already_found_issues = already_found_issues | {group_key}
            feedback_parts.append(f"+0.04 new issue found: '{group_key}'.")

    # Line coverage — credit first hit on each expected line
    expected_lines = set(task["expected_comment_lines"])
    this_step_lines: Set[int] = set()
    for c in inline_comments:
        ln = c.get("line_number", -1)
        if ln in expected_lines and ln not in already_hit_lines:
            step_reward += 0.03
            already_hit_lines = already_hit_lines | {ln}
            feedback_parts.append(f"+0.03 new correct line commented: {ln}.")
        elif ln in this_step_lines:
            # Duplicate within same step
            step_reward -= 0.02
            feedback_parts.append(f"-0.02 duplicate comment on line {ln}.")
        this_step_lines.add(ln)

    # Exploit guard
    if approve and task["expected_severity"] in ("critical", "major"):
        step_reward -= 0.20
        feedback_parts.append("-0.20 penalty: approved critical/major PR.")

    # Action cost
    step_reward -= 0.005
    step_reward = round(max(-1.0, step_reward), 4)

    feedback = " | ".join(feedback_parts) if feedback_parts else "No new discoveries."
    return step_reward, already_found_issues, already_hit_lines, feedback


# ─── Environment class ────────────────────────────────────────────────────────

class CodeReviewEnvironment:
    """
    OpenEnv-compatible environment for code review triage.

    Each episode = one task scenario.
    The agent gets up to MAX_STEPS attempts to review the same diff.

    Reward design:
      - Intermediate steps: dense signal via _dense_reward (partial credit for
        each new discovery — severity, approve, key issues, line hits)
      - Terminal step: the full grader score (grade_action) to give a clean
        0.0–1.0 summary signal and anchor cumulative reward
    """

    SUPPORTS_CONCURRENT_SESSIONS = True
    MAX_STEPS = 3

    def __init__(self):
        self._task_id: str = "task_easy"
        self._task: Dict[str, Any] = TASKS["task_easy"]
        self._episode_id: str = ""
        self._step_count: int = 0
        self._best_score: float = 0.0
        self._last_feedback: str = ""
        # Track what has already been credited for dense rewards
        self._found_issues: Set[str] = set()
        self._hit_lines: Set[int] = set()

    # ── Public interface ──────────────────────────────────────────────────────

    def reset(
        self,
        task_id: Optional[str] = None,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Start a new episode. Returns an observation dict."""
        if task_id and task_id in TASKS:
            self._task_id = task_id
        else:
            self._task_id = "task_easy"

        self._task = TASKS[self._task_id]
        self._episode_id = episode_id or str(uuid.uuid4())
        self._step_count = 0
        self._best_score = 0.0
        self._last_feedback = ""
        self._found_issues = set()
        self._hit_lines = set()

        return self._build_obs(done=False, reward=None, feedback="")

    def step(self, action: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Process one agent action.

        Intermediate steps: dense step reward (partial credit per new discovery).
        Terminal step: full grader score (grade_action) used as final reward.
        """
        self._step_count += 1

        final_score, grade_feedback = grade_action(action, self._task)
        self._best_score = max(self._best_score, final_score)

        done = (final_score >= 0.85) or (self._step_count >= self.MAX_STEPS)

        if done:
            # Terminal: return the definitive grader score
            reward = round(self._best_score, 4)
            feedback = grade_feedback
        else:
            # Intermediate: return dense partial-credit signal
            step_reward, self._found_issues, self._hit_lines, dense_feedback = _dense_reward(
                action,
                self._task,
                self._found_issues,
                self._hit_lines,
                self._step_count,
            )
            reward = step_reward
            feedback = dense_feedback

        self._last_feedback = feedback

        return {
            **self._build_obs(done=done, reward=reward, feedback=feedback),
            "done": done,
            "reward": reward,
        }

    def state(self) -> Dict[str, Any]:
        return {
            "episode_id": self._episode_id,
            "step_count": self._step_count,
            "task_id": self._task_id,
            "task_difficulty": self._task["difficulty"],
            "max_steps": self.MAX_STEPS,
            "attempts_used": self._step_count,
            "best_score": self._best_score,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_obs(
        self, done: bool, reward: Optional[float], feedback: str
    ) -> Dict[str, Any]:
        task = self._task
        return {
            "observation": {
                "task_id": self._task_id,
                "task_difficulty": task["difficulty"],
                "pr_title": task["pr_title"],
                "pr_description": task["pr_description"],
                "diff": task["diff"],
                "file_context": task.get("file_context", ""),
                "feedback": feedback,
                "current_score": self._best_score,
                "legal_actions": ["critical", "major", "minor", "approved"],
            },
            "done": done,
            "reward": reward,
        }
