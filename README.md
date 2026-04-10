---
title: Code Review Triage
emoji: 🔍
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
tags:
  - openenv
  - code-review
  - reinforcement-learning
  - real-world
---

# Code Review Triage — OpenEnv Environment

An RL environment where an AI agent learns to **triage pull request diffs**: detect bugs, security vulnerabilities, and architectural problems — and produce structured code reviews with severity labels and inline comments.

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://huggingface.co/spaces/suhastumati03/code-review-triage
cd code-review-triage

# 2. Build and run the Docker container
docker build -t code-review-triage .
docker run -p 8000:8000 code-review-triage

# 3. Verify the server is healthy
curl http://localhost:8000/health
# {"status": "healthy", "environment": "code-review-triage"}

# 4. Run the baseline agent
export HF_TOKEN=hf_...                            # required
export SERVER_URL=http://localhost:8000
# API_BASE_URL and MODEL_NAME have defaults (HF router + Qwen2.5-72B)
python inference.py
```

### Baseline Scores (`Qwen/Qwen2.5-72B-Instruct` via HF router, `temperature=0`)

| Task | Score | Steps | Success |
|------|-------|-------|---------|
| `task_easy` | ~0.85 | 1 | ✓ |
| `task_medium` | ~0.78 | 2 | ✓ |
| `task_hard` | ~0.58 | 3 | — |
| **Average** | **~0.74** | | |

Scores are deterministic: re-running produces identical results.

---

## Motivation

Code review is a task every software team performs daily. It requires:
- Recognising bug patterns (null dereferences, off-by-ones)
- Identifying security vulnerabilities (SQL injection, auth bypass)
- Evaluating architecture (N+1 queries, race conditions, missing error handling)

Existing benchmarks evaluate LLMs on code *generation*. This environment evaluates agents on code *review* — a distinct, high-value, under-explored capability with immediate practical utility.

---

## Action Space

```python
CodeReviewAction(
    severity: str,                         # "critical" | "major" | "minor" | "approved"
    inline_comments: List[InlineComment],  # [{line_number: int, comment: str}, ...]
    summary: str,                          # 1-3 sentence overall assessment
    approve: bool,                         # True = merge, False = request changes
)
```

Severity definitions:
- **critical** — security vulnerabilities, null/crash bugs, data loss risk
- **major** — logic errors, significant performance problems, missing error handling
- **minor** — style issues, nit-picks
- **approved** — code is correct and ready to merge

## Observation Space

```python
CodeReviewObservation(
    task_id: str,                  # "task_easy" | "task_medium" | "task_hard"
    task_difficulty: str,          # "easy" | "medium" | "hard"
    pr_title: str,                 # Pull request title
    pr_description: str,           # Author's stated intent
    diff: str,                     # Unified diff of the PR
    file_context: str,             # Surrounding code (imports, class def)
    feedback: str,                 # Grader feedback from previous step
    current_score: float,          # Best score so far this episode (0.0–1.0)
    legal_actions: List[str],      # Valid severity labels ["critical","major","minor","approved"]
    done: bool,                    # Episode over
    reward: Optional[float],       # Step reward (None on reset)
)
```

---

## Tasks

| Task | Difficulty | What to Find |
|------|-----------|--------------|
| `task_easy` | Easy | `AttributeError`: `display_name` can be `None`, `.upper()` crashes |
| `task_medium` | Medium | SQL injection via f-string interpolation in two Flask routes |
| `task_hard` | Hard | N+1 query loop + race condition on shared list + SQL injection |

### Ground Truth

**task_easy**
- Expected severity: `critical`, approve: `False`
- Key issues: null dereference, `display_name`, `AttributeError`, `upper()`
- Key lines: line 4 (`name.upper()`)

**task_medium**
- Expected severity: `critical`, approve: `False`
- Key issues: SQL injection, f-string, parameterized queries, user input
- Key lines: lines 4, 5 (search route), lines 10, 11 (get-by-id route)

**task_hard**
- Expected severity: `critical`, approve: `False`
- Key issues: N+1 loop, race condition, `shared_state`, SQL injection, missing error handling, reuse `ClientSession`
- Key lines: lines 5–7 (N+1 + SQLi), lines 14 (session per call), lines 17–19 (race), line 25 (SQLi in notify_single)

---

## Reward Design

### Terminal step — `grade_action()` (full grader score, 0.0–1.0)

| Component | Weight | Description |
|-----------|--------|-------------|
| Severity label | 30% | Exact match (`critical`/`major` also gives 50% partial) |
| Approve/reject | 20% | Correct merge decision |
| Key issues detected | 30% | Keyword coverage across summary + all comments |
| Inline line coverage | 20% | Fraction of ground-truth diff lines commented |
| **Exploit penalty** | −0.20 | Approving a PR that has a critical/major bug |

A perfect answer scores **exactly 1.0**.

### Intermediate steps — `_dense_reward()` (partial-credit signal)

| Signal | Value | Condition |
|--------|-------|-----------|
| Correct severity | +0.10 | First time only |
| Correct severity (partial) | +0.05 | First time, `major`/`critical` mix |
| Correct approve/reject | +0.05 | First time only |
| New key issue found | +0.04 | Per keyword, first mention only |
| New ground-truth line commented | +0.03 | Per line, first hit only |
| Exploit: approve critical PR | −0.20 | Any step |
| Duplicate comment on same line | −0.02 | Per duplicate within a step |
| Action cost | −0.005 | Per step (discourages padding) |

Rewards are clamped to `[−1.0, 1.0]` per step; terminal score clamped to `[0.0, 1.0]`.

---

## Setup

### Local (no Docker)

```bash
pip install -r requirements.txt
uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload
```

### Docker

```bash
docker build -t code-review-triage .
docker run -p 8000:8000 code-review-triage
```

### HF Space

```bash
huggingface-cli repo create code-review-triage --type space --sdk docker
git remote add hf https://huggingface.co/spaces/suhastumati03/code-review-triage
git push hf master
```

Set Space variables (`Settings → Variables`):
- `HF_TOKEN` — your Hugging Face token (required)
- `API_BASE_URL` — `https://router.huggingface.co/v1` (default)
- `MODEL_NAME` — `Qwen/Qwen2.5-72B-Instruct` (default)
- `SERVER_URL` — `http://localhost:8000` (default, points to the container itself)
---

## Running the Baseline

```bash
export HF_TOKEN=hf_...
# Optional overrides (defaults shown):
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export SERVER_URL=http://localhost:8000

python inference.py
```

**Expected stdout (exact format):**
```
[START] task=task_easy env=code-review-triage model=Qwen/Qwen2.5-72B-Instruct
[STEP] step=1 action={"severity":"critical","inline_comments":[...],"summary":"...","approve":false} reward=0.85 done=true error=null
[END] success=true steps=1 score=0.85 rewards=0.85
```

---

## Python Client

```python
from client import CodeReviewEnv, CodeReviewAction, InlineComment

with CodeReviewEnv(base_url="http://localhost:8000").sync() as env:
    result = env.reset(task_id="task_easy")
    print(result.observation.diff)
    print(result.observation.legal_actions)  # ["critical", "major", "minor", "approved"]

    action = CodeReviewAction(
        severity="critical",
        inline_comments=[InlineComment(line_number=4, comment="name may be None — AttributeError on .upper()")],
        summary="display_name is Optional[str] but .upper() is called unconditionally — crashes for legacy accounts.",
        approve=False,
    )
    result = env.step(action)
    print(f"Reward: {result.reward}  |  Feedback: {result.observation.feedback}")
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness probe |
| `/tasks` | GET | List all 3 tasks with difficulty |
| `/reset` | POST | Start a new episode `{"task_id": "task_easy"}` |
| `/step` | POST | Submit a review `{"action": {...}, "task_id": "task_easy"}` |
| `/state` | GET | Episode metadata (`episode_id`, `step_count`, `best_score`) |
| `/ws` | WS | WebSocket interface (`{"method": "reset/step/state", ...}`) |

---

## Project Structure

```
.
├── models.py              # Typed Pydantic models (Action, Observation, State)
├── client.py              # Python client (WebSocket + HTTP fallback)
├── server/
│   ├── environment.py     # 3 tasks, grader, dense rewards, exploit guard
│   └── app.py             # FastAPI server (REST + WebSocket)
├── inference.py           # Baseline inference script
├── openenv.yaml           # OpenEnv manifest
├── Dockerfile             # Container definition
└── requirements.txt       # Pinned dependencies
```

## Hardware Requirements

The environment server has no external dependencies (no LLM calls server-side). It runs comfortably within **2 vCPU / 8 GB RAM**. The full baseline (`MAX_STEPS=3`, 3 tasks) completes in under **3 minutes** on the HF router.
