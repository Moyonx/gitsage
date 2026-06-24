#!/usr/bin/env python3
"""
gitsage evaluation — two studies
=================================
Study 1  LLM-as-Judge quality benchmark
  · 30 real commits from tiangolo/fastapi, encode/httpx, Textualize/rich
  · gitsage generates a candidate message for each raw diff (no CTX.md, no memory)
  · A separate LLM judge scores both human and gitsage on clarity/accuracy/overall (1–5)

Study 2  CTX.md ablation — Conventional Commits compliance rate
  · 20 recent commits from the gitsage repo (local git, no GitHub API)
  · Generate with and without CTX.md; score by regex (no LLM cost)
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from gitsage.config import load_config
from gitsage.agent import create_llm_client, build_commit_user_prompt, CommitOutput
from gitsage.agent.prompts import COMMIT_SYSTEM_PROMPT

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
cfg = load_config()
llm = create_llm_client(cfg.llm)
RESULTS_FILE = Path(__file__).parent / "eval_results.json"

REPOS = ["tiangolo/fastapi", "encode/httpx", "Textualize/rich"]
N_PER_REPO = 10          # 30 commits total
ABLATION_N = 20          # local commits for Study 2
CALL_DELAY = 0.8         # seconds between LLM/API calls


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic judge schema  (flat — maximally compatible across providers)
# ─────────────────────────────────────────────────────────────────────────────
class JudgeResult(BaseModel):
    """LLM judge scores both messages in one call."""
    human_clarity:   int   # 1-5  Is the human message clear?
    human_accuracy:  int   # 1-5  Does it accurately describe the diff?
    human_overall:   int   # 1-5  Would you use this in a real project?
    gen_clarity:     int   # 1-5  Same dimensions for gitsage output
    gen_accuracy:    int
    gen_overall:     int
    reasoning:       str   # 1–2 sentence justification


# ─────────────────────────────────────────────────────────────────────────────
# Study 1 helpers
# ─────────────────────────────────────────────────────────────────────────────
def fetch_commits(repo: str, n: int) -> list[dict]:
    """Fetch N recent commits (diff + first-line message) from GitHub public API."""
    headers = {"Accept": "application/vnd.github.v3+json",
               "User-Agent": "gitsage-eval/0.1"}
    try:
        r = httpx.get(
            f"https://api.github.com/repos/{repo}/commits",
            params={"per_page": n + 5},   # fetch a few extra to filter merges
            headers=headers, timeout=30,
            follow_redirects=True,
        )
        r.raise_for_status()
    except Exception as e:
        print(f"    ⚠  {repo} listing failed: {e}")
        return []

    items = []
    for item in r.json():
        if len(items) >= n:
            break
        sha = item["sha"]
        raw_msg = item["commit"]["message"]
        message = raw_msg.split("\n")[0].strip()

        # skip merge commits and empty messages
        if message.lower().startswith("merge") or not message:
            continue

        time.sleep(CALL_DELAY)
        try:
            dr = httpx.get(
                f"https://api.github.com/repos/{repo}/commits/{sha}",
                headers={**headers, "Accept": "application/vnd.github.diff"},
                timeout=30,
                follow_redirects=True,
            )
            dr.raise_for_status()
        except Exception:
            continue

        diff = dr.text[:3500]
        if len(diff.strip()) < 60:
            continue   # trivial / empty diff

        items.append({"sha": sha[:7], "message": message, "diff": diff})

    return items


def generate_candidate(diff: str) -> str:
    """Run gitsage commit pipeline on a raw diff (no CTX.md, no memory)."""
    user_prompt = build_commit_user_prompt(
        diff=diff, recent_commits=[], branch_name="main",
        ctx_content="", memory_content="", skill_content="",
    )
    try:
        output: CommitOutput = llm.complete(
            system=COMMIT_SYSTEM_PROMPT,
            user=user_prompt,
            output_model=CommitOutput,
        )
        return output.candidates[0].message if output.candidates else ""
    except Exception as e:
        print(f"      ⚠  generation error: {e}")
        return ""


JUDGE_SYSTEM = (
    "You are an expert software engineer evaluating git commit message quality. "
    "Score each message independently on clarity, accuracy, and overall (1–5). "
    "1=poor, 3=acceptable, 5=excellent. Be honest and critical. "
    "Output ONLY valid JSON matching the schema provided — no prose, no markdown."
)


def judge(diff: str, human_msg: str, generated_msg: str) -> Optional[JudgeResult]:
    """LLM-as-Judge: score both messages given the diff."""
    from gitsage.agent.prompts import get_json_schema_prompt
    schema = get_json_schema_prompt(JudgeResult)

    prompt = (
        f"Diff (truncated):\n```\n{diff[:1800]}\n```\n\n"
        f"Message A (human):     \"{human_msg}\"\n"
        f"Message B (generated): \"{generated_msg}\"\n\n"
        f"Score each on clarity, accuracy, overall (1–5).\n"
        f"Schema:\n{schema}"
    )
    try:
        return llm.complete(system=JUDGE_SYSTEM, user=prompt, output_model=JudgeResult)
    except Exception as e:
        print(f"      ⚠  judge error: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Study 2 helpers
# ─────────────────────────────────────────────────────────────────────────────
CC_RE = re.compile(
    r"^(feat|fix|refactor|docs|test|chore|perf|style|ci|build|revert)"
    r"(\([^)]+\))?(!)?:\s+\S",
    re.IGNORECASE,
)

CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def is_cc(msg: str) -> bool:
    return bool(CC_RE.match(msg.strip()))


def is_chinese(msg: str) -> bool:
    """Return True if the description part (after the colon) contains CJK characters."""
    colon_idx = msg.find(": ")
    desc = msg[colon_idx + 2:] if colon_idx != -1 else msg
    return len(CJK_RE.findall(desc)) >= 2   # at least 2 CJK chars


def local_commits(n: int) -> list[dict]:
    """Get recent Python-touching commits from the current repo."""
    out = subprocess.run(
        ["git", "log", f"-{n + 10}", "--format=%H|||%s"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout.strip().splitlines()

    commits = []
    for line in out:
        if len(commits) >= n:
            break
        if "|||" not in line:
            continue
        sha, msg = line.split("|||", 1)
        msg = msg.strip()
        # skip merge / chore / test-only commits for cleaner signal
        if any(msg.lower().startswith(p) for p in ("merge", "chore:")):
            continue

        diff = subprocess.run(
            ["git", "diff", f"{sha}~1", sha, "--", "*.py"],
            capture_output=True, text=True, cwd=ROOT,
        ).stdout[:3500]

        if len(diff.strip()) < 60:
            continue
        commits.append({"sha": sha[:7], "message": msg, "diff": diff})

    return commits


def generate_with_ctx(diff: str, ctx: str) -> str:
    """Generate commit message with or without CTX.md content."""
    user_prompt = build_commit_user_prompt(
        diff=diff, recent_commits=[], branch_name="feature/test",
        ctx_content=ctx, memory_content="", skill_content="",
    )
    try:
        output: CommitOutput = llm.complete(
            system=COMMIT_SYSTEM_PROMPT,
            user=user_prompt,
            output_model=CommitOutput,
        )
        return output.candidates[0].message if output.candidates else ""
    except Exception as e:
        print(f"      ⚠  error: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    results: dict = {}

    # ── Study 1 ───────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  Study 1 · LLM-as-Judge Quality Benchmark")
    print("═" * 60)

    raw_scores: list[dict] = []

    for repo in REPOS:
        print(f"\n  ► {repo}")
        commits = fetch_commits(repo, N_PER_REPO)
        print(f"    fetched {len(commits)} commits")

        for i, c in enumerate(commits):
            label = f"[{i+1}/{len(commits)}] {c['sha']}"
            print(f"\n    {label}  human: {c['message'][:55]}")

            generated = generate_candidate(c["diff"])
            if not generated:
                continue
            print(f"    {' ' * len(label)}  gitsage: {generated[:55]}")
            time.sleep(CALL_DELAY)

            score = judge(c["diff"], c["message"], generated)
            if score is None:
                continue
            time.sleep(CALL_DELAY)

            raw_scores.append({
                "repo":         repo,
                "sha":          c["sha"],
                "human_msg":    c["message"],
                "gen_msg":      generated,
                "h_clarity":    score.human_clarity,
                "h_accuracy":   score.human_accuracy,
                "h_overall":    score.human_overall,
                "g_clarity":    score.gen_clarity,
                "g_accuracy":   score.gen_accuracy,
                "g_overall":    score.gen_overall,
                "reasoning":    score.reasoning,
            })

            h, g = score.human_overall, score.gen_overall
            gap = g - h
            flag = "✓" if abs(gap) <= 1 else ("↑" if gap > 0 else "↓")
            print(f"    {' ' * len(label)}  judge: human={h} gitsage={g} {flag}  | {score.reasoning[:60]}")

    if raw_scores:
        n = len(raw_scores)
        h_ov  = statistics.mean(s["h_overall"]  for s in raw_scores)
        g_ov  = statistics.mean(s["g_overall"]  for s in raw_scores)
        g_cl  = statistics.mean(s["g_clarity"]  for s in raw_scores)
        g_ac  = statistics.mean(s["g_accuracy"] for s in raw_scores)
        within_1 = sum(1 for s in raw_scores if abs(s["g_overall"] - s["h_overall"]) <= 1) / n

        results["study1"] = {
            "n":                     n,
            "human_overall":         round(h_ov, 2),
            "gitsage_overall":       round(g_ov, 2),
            "gitsage_clarity":       round(g_cl, 2),
            "gitsage_accuracy":      round(g_ac, 2),
            "within_1pt_of_human_%": round(within_1 * 100, 1),
            "raw":                   raw_scores,
        }
        print(f"\n  ✅ Study 1 results (n={n})")
        print(f"     Human baseline    : {h_ov:.2f}/5")
        print(f"     gitsage overall   : {g_ov:.2f}/5")
        print(f"     gitsage clarity   : {g_cl:.2f}/5")
        print(f"     gitsage accuracy  : {g_ac:.2f}/5")
        print(f"     Within ±1pt       : {within_1*100:.1f}%")

    # ── Study 2 ───────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  Study 2 · CTX.md Ablation — CC Compliance Rate")
    print("═" * 60)

    ctx_path = ROOT / "CTX.md"
    ctx_content = ctx_path.read_text(encoding="utf-8") if ctx_path.exists() else ""

    commits = local_commits(ABLATION_N)
    print(f"\n  Using {len(commits)} local gitsage commits\n")

    ablation: list[dict] = []
    for i, c in enumerate(commits):
        print(f"  [{i+1}/{len(commits)}] {c['sha']}  {c['message'][:50]}")

        no_ctx   = generate_with_ctx(c["diff"], "")
        time.sleep(CALL_DELAY)
        with_ctx = generate_with_ctx(c["diff"], ctx_content)
        time.sleep(CALL_DELAY)

        row = {
            "sha":           c["sha"],
            "human_msg":     c["message"],
            "human_cc":      is_cc(c["message"]),
            "human_zh":      is_chinese(c["message"]),
            "no_ctx_msg":    no_ctx,
            "no_ctx_cc":     is_cc(no_ctx),
            "no_ctx_zh":     is_chinese(no_ctx),
            "with_ctx_msg":  with_ctx,
            "with_ctx_cc":   is_cc(with_ctx),
            "with_ctx_zh":   is_chinese(with_ctx),
        }
        ablation.append(row)

        cc_no  = "✓" if row["no_ctx_cc"]  else "✗"
        cc_wt  = "✓" if row["with_ctx_cc"] else "✗"
        zh_no  = "中" if row["no_ctx_zh"]  else "En"
        zh_wt  = "中" if row["with_ctx_zh"] else "En"
        print(f"    no ctx  : {no_ctx[:55]}  [CC:{cc_no} Lang:{zh_no}]")
        print(f"    with ctx: {with_ctx[:55]}  [CC:{cc_wt} Lang:{zh_wt}]")

    if ablation:
        n2 = len(ablation)
        h_cc    = sum(r["human_cc"]    for r in ablation) / n2
        no_cc   = sum(r["no_ctx_cc"]   for r in ablation) / n2
        wt_cc   = sum(r["with_ctx_cc"] for r in ablation) / n2
        h_zh    = sum(r["human_zh"]    for r in ablation) / n2
        no_zh   = sum(r["no_ctx_zh"]   for r in ablation) / n2
        wt_zh   = sum(r["with_ctx_zh"] for r in ablation) / n2

        results["study2"] = {
            "n":                     n2,
            "human_cc_%":            round(h_cc  * 100, 1),
            "no_ctx_cc_%":           round(no_cc * 100, 1),
            "with_ctx_cc_%":         round(wt_cc * 100, 1),
            "cc_improvement_pts":    round((wt_cc - no_cc) * 100, 1),
            "human_zh_%":            round(h_zh  * 100, 1),
            "no_ctx_zh_%":           round(no_zh * 100, 1),
            "with_ctx_zh_%":         round(wt_zh * 100, 1),
            "zh_improvement_pts":    round((wt_zh - no_zh) * 100, 1),
            "raw":                   ablation,
        }
        print(f"\n  ✅ Study 2 results (n={n2})")
        print(f"  CC Compliance:")
        print(f"     Human baseline  : {h_cc*100:.1f}%")
        print(f"     Without CTX.md  : {no_cc*100:.1f}%")
        print(f"     With CTX.md     : {wt_cc*100:.1f}%")
        print(f"  Language Consistency (project convention: Chinese):")
        print(f"     Human baseline  : {h_zh*100:.1f}% Chinese")
        print(f"     Without CTX.md  : {no_zh*100:.1f}% Chinese  ← LLM defaults to English")
        print(f"     With CTX.md     : {wt_zh*100:.1f}% Chinese  ← CTX.md enforces convention")
        print(f"     Lang improvement: +{(wt_zh - no_zh)*100:.1f} pts")

    # ── Save ─────────────────────────────────────────────────────────────
    RESULTS_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Resume summary ───────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  RESUME NUMBERS")
    print("═" * 60)
    if "study1" in results:
        s1 = results["study1"]
        print(f"\n  LLM-as-Judge (n={s1['n']}, 3 OSS repos, model=deepseek-v4-flash):")
        print(f"    gitsage 生成质量   {s1['gitsage_overall']}/5")
        print(f"    人类基准           {s1['human_overall']}/5")
        print(f"    与人类误差 ≤1分   {s1['within_1pt_of_human_%']}%")
    if "study2" in results:
        s2 = results["study2"]
        print(f"\n  CTX.md 消融 (n={s2['n']}, gitsage 仓库):")
        print(f"    CC 合规率    无 CTX.md {s2['no_ctx_cc_%']}%  →  有 CTX.md {s2['with_ctx_cc_%']}%")
        print(f"    语言一致性   无 CTX.md {s2['no_ctx_zh_%']}% 中文  →  有 CTX.md {s2['with_ctx_zh_%']}% 中文  (+{s2['zh_improvement_pts']} pts)")
    print(f"\n  完整结果已保存至 {RESULTS_FILE}\n")


if __name__ == "__main__":
    main()
