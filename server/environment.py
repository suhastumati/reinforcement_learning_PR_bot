"""
Code Review Triage — Environment Logic (no openenv-core dependency)
"""

import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

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
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["none", "null"],
            ["attributeerror", "attribute error"],
            ["display_name"],
            ["upper"],
            ["optional", "can be none", "may be none"],
        ],
        "expected_comment_lines": [4],
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
            ["sql injection", "sqli"],
            ["parameterized", "parameterise", "parameterize", "prepared statement"],
            ["sanitize", "sanitise", "escape", "validate"],
            ["f-string", "format string", "string interpolation"],
            ["user input", "untrusted", "request.args"],
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
            ["n+1", "n plus 1", "per-user query", "query per user"],
            ["batch", "bulk", "fetch_all", "single query"],
            ["race condition", "race", "shared_state", "concurrent write"],
            ["sql injection", "sqli", "f-string", "parameterized"],
            ["error handling", "exception", "try", "except"],
            ["clientsession", "session per", "reuse session", "aiohttp.ClientSession"],
        ],
        "expected_comment_lines": [5, 6, 7, 14, 17, 18, 19, 25],
    },

    "task_idor": {
        "difficulty": "medium",
        "pr_title": "Add document download endpoint",
        "pr_description": (
            "Adds a REST endpoint to download user documents. "
            "Documents are stored in /uploads/<doc_id>.pdf."
        ),
        "file_context": (
            "# routes/documents.py\n"
            "from flask import request, send_file, jsonify, g\n"
            "import os\n"
            "import db  # db.query(sql) -> list[dict]\n"
            "# g.user_id is the authenticated user's ID (set by auth middleware)\n"
        ),
        "diff": (
            "@@ -0,0 +1,18 @@\n"
            "+@app.route('/api/documents/<int:doc_id>/download')\n"
            "+def download_document(doc_id):\n"
            "+    # Fetch document metadata\n"
            "+    rows = db.query(f'SELECT * FROM documents WHERE id = {doc_id}')\n"
            "+    if not rows:\n"
            "+        return jsonify({'error': 'Not found'}), 404\n"
            "+    doc = rows[0]\n"
            "+    # Return the file directly\n"
            "+    filepath = f'/uploads/{doc_id}.pdf'\n"
            "+    return send_file(filepath)\n"
            "+\n"
            "+@app.route('/api/documents')\n"
            "+def list_documents():\n"
            "+    user_id = request.args.get('user_id')\n"
            "+    rows = db.query(f'SELECT id, name FROM documents WHERE owner_id = {user_id}')\n"
            "+    return jsonify(rows)\n"
        ),
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["idor", "insecure direct object", "authorization", "ownership check"],
            ["sql injection", "sqli", "parameterized"],
            ["user_id", "owner_id", "authentication", "g.user_id"],
            ["access control", "permission", "authoriz"],
            ["f-string", "format string", "string interpolation"],
        ],
        "expected_comment_lines": [4, 9, 14, 15],
    },

    "task_path_traversal": {
        "difficulty": "hard",
        "pr_title": "Add file upload and preview feature",
        "pr_description": (
            "Adds a file upload endpoint and a preview endpoint that reads "
            "uploaded files. Files are stored under /var/uploads/."
        ),
        "file_context": (
            "# routes/files.py\n"
            "import os\n"
            "from flask import request, jsonify, send_file\n"
            "UPLOAD_DIR = '/var/uploads'\n"
        ),
        "diff": (
            "@@ -0,0 +1,22 @@\n"
            "+@app.route('/api/files/upload', methods=['POST'])\n"
            "+def upload_file():\n"
            "+    f = request.files['file']\n"
            "+    filename = f.filename  # User-controlled filename — not sanitized\n"
            "+    save_path = os.path.join(UPLOAD_DIR, filename)\n"
            "+    f.save(save_path)\n"
            "+    return jsonify({'path': filename})\n"
            "+\n"
            "+@app.route('/api/files/preview')\n"
            "+def preview_file():\n"
            "+    filename = request.args.get('filename', '')\n"
            "+    filepath = os.path.join(UPLOAD_DIR, filename)\n"
            "+    if not os.path.exists(filepath):\n"
            "+        return jsonify({'error': 'File not found'}), 404\n"
            "+    with open(filepath, 'r') as fh:\n"
            "+        content = fh.read()\n"
            "+    return jsonify({'content': content})\n"
            "+\n"
            "+@app.route('/api/files/delete', methods=['DELETE'])\n"
            "+def delete_file():\n"
            "+    filename = request.args.get('filename')\n"
            "+    os.remove(os.path.join(UPLOAD_DIR, filename))\n"
            "+    return jsonify({'deleted': True})\n"
        ),
        "expected_severity": "critical",
        "expected_approve": False,
        "key_issues": [
            ["path traversal", "directory traversal", "../", "dot dot"],
            ["sanitize", "sanitise", "basename", "secure_filename", "validate"],
            ["filename", "user-controlled", "unsanitized", "untrusted input"],
            ["authentication", "authorization", "unauthenticated", "no auth"],
            ["arbitrary file", "read file", "overwrite", "delete any"],
        ],
        "expected_comment_lines": [4, 5, 11, 12, 21, 22],
    },
}

TASK_ORDER = ["task_easy", "task_medium", "task_hard", "task_idor", "task_path_traversal"]


def _keywords_hit(text: str, keyword_groups: list) -> float:
    text_lower = text.lower()
    hits = sum(
        1 for group in keyword_groups
        if any(kw in text_lower for kw in (group if isinstance(group, list) else [group]))
    )
    return hits / max(len(keyword_groups), 1)


def grade_action(action_dict: Dict[str, Any], task: Dict[str, Any]) -> Tuple[float, str]:
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

    if severity == task["expected_severity"]:
        severity_score = 1.0
        feedback_parts.append("Severity label correct.")
    elif severity in ("major", "critical") and task["expected_severity"] in ("major", "critical"):
        severity_score = 0.5
        feedback_parts.append(f"Severity close but expected '{task['expected_severity']}'.")
    else:
        feedback_parts.append(f"Wrong severity — expected '{task['expected_severity']}', got '{severity}'.")

    if approve == task["expected_approve"]:
        approve_score = 1.0
        feedback_parts.append("Approve decision correct.")
    else:
        decision = "approve" if task["expected_approve"] else "request changes"
        feedback_parts.append(f"Wrong decision — should {decision}.")

    issue_score = _keywords_hit(all_comment_text, task["key_issues"])
    feedback_parts.append(f"Key issues detected: {int(issue_score * 100)}%.")

    expected_lines = set(task["expected_comment_lines"])
    commented_lines = set(c.get("line_number", -1) for c in inline_comments)
    if expected_lines:
        line_score = len(expected_lines & commented_lines) / len(expected_lines)
    feedback_parts.append(f"Line coverage: {int(line_score * 100)}% of key lines commented.")

    total = (
        0.30 * severity_score
        + 0.20 * approve_score
        + 0.30 * issue_score
        + 0.20 * line_score
    )

    if approve and task["expected_severity"] in ("critical", "major"):
        total -= 0.20
        feedback_parts.append("Penalty: approved a PR with critical/major issues.")

    total = round(max(0.0, min(1.0, total)), 4)
    return total, " | ".join(feedback_parts)


def _dense_reward(
    action_dict: Dict[str, Any],
    task: Dict[str, Any],
    already_found_issues: Set[str],
    already_hit_lines: Set[int],
    step_count: int,
) -> Tuple[float, Set[str], Set[int], str]:
    step_reward = 0.0
    feedback_parts: List[str] = []

    severity = action_dict.get("severity", "").lower().strip()
    approve = action_dict.get("approve", True)
    summary = action_dict.get("summary", "")
    inline_comments = action_dict.get("inline_comments", [])
    all_text = (summary + " " + " ".join(c.get("comment", "") for c in inline_comments)).lower()

    if severity == task["expected_severity"] and "_severity" not in already_found_issues:
        step_reward += 0.10
        already_found_issues = already_found_issues | {"_severity"}
        feedback_parts.append("+0.10 severity correct (first time).")
    elif severity in ("major", "critical") and task["expected_severity"] in ("major", "critical") \
            and "_severity_partial" not in already_found_issues:
        step_reward += 0.05
        already_found_issues = already_found_issues | {"_severity_partial"}
        feedback_parts.append("+0.05 severity close (first time).")

    if approve == task["expected_approve"] and "_approve" not in already_found_issues:
        step_reward += 0.05
        already_found_issues = already_found_issues | {"_approve"}
        feedback_parts.append("+0.05 approve decision correct (first time).")

    for group in task["key_issues"]:
        synonyms = group if isinstance(group, list) else [group]
        group_key = synonyms[0]
        if any(kw in all_text for kw in synonyms) and group_key not in already_found_issues:
            step_reward += 0.04
            already_found_issues = already_found_issues | {group_key}
            feedback_parts.append(f"+0.04 new issue found: '{group_key}'.")

    expected_lines = set(task["expected_comment_lines"])
    this_step_lines: Set[int] = set()
    for c in inline_comments:
        ln = c.get("line_number", -1)
        if ln in expected_lines and ln not in already_hit_lines:
            step_reward += 0.03
            already_hit_lines = already_hit_lines | {ln}
            feedback_parts.append(f"+0.03 new correct line commented: {ln}.")
        elif ln in this_step_lines:
            step_reward -= 0.02
            feedback_parts.append(f"-0.02 duplicate comment on line {ln}.")
        this_step_lines.add(ln)

    if approve and task["expected_severity"] in ("critical", "major"):
        step_reward -= 0.20
        feedback_parts.append("-0.20 penalty: approved critical/major PR.")

    step_reward -= 0.005
    step_reward = round(max(-1.0, step_reward), 4)
    feedback = " | ".join(feedback_parts) if feedback_parts else "No new discoveries."
    return step_reward, already_found_issues, already_hit_lines, feedback


class CodeReviewEnvironment:
    SUPPORTS_CONCURRENT_SESSIONS = True
    MAX_STEPS = 3

    def __init__(self):
        self._task_id = "task_easy"
        self._task = TASKS["task_easy"]
        self._episode_id = ""
        self._step_count = 0
        self._best_score = 0.0
        self._last_feedback = ""
        self._found_issues: Set[str] = set()
        self._hit_lines: Set[int] = set()

    def reset(self, task_id=None, seed=None, episode_id=None, **kwargs) -> Dict[str, Any]:
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

    def step(self, action_dict: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        self._step_count += 1
        final_score, grade_feedback = grade_action(action_dict, self._task)
        self._best_score = max(self._best_score, final_score)
        done = (final_score >= 0.85) or (self._step_count >= self.MAX_STEPS)

        if done:
            reward = round(self._best_score, 4)
            feedback = grade_feedback
        else:
            step_reward, self._found_issues, self._hit_lines, dense_feedback = _dense_reward(
                action_dict, self._task, self._found_issues, self._hit_lines, self._step_count,
            )
            reward = round(max(0.0, min(1.0, step_reward)), 4)
            feedback = dense_feedback

        self._last_feedback = feedback
        return self._build_obs(done=done, reward=reward, feedback=feedback)

    def get_state(self) -> Dict[str, Any]:
        return {
            "episode_id": self._episode_id,
            "step_count": self._step_count,
            "task_id": self._task_id,
            "task_difficulty": self._task["difficulty"],
            "max_steps": self.MAX_STEPS,
            "attempts_used": self._step_count,
            "best_score": self._best_score,
        }

    def _build_obs(self, done: bool, reward, feedback: str) -> Dict[str, Any]:
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
