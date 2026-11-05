"""Check whether an opted-in workflow has started on schedule."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def minutes_since(started_at, now):
    return (now - datetime.fromisoformat(started_at.replace("Z", "+00:00"))).total_seconds() / 60


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    workflow = os.environ["GUARDIAN_WATCH_WORKFLOW"]
    branch = os.environ["GUARDIAN_DEFAULT_BRANCH"]
    limit = int(os.environ.get("GUARDIAN_MAX_AGE_MINUTES") or 180)
    if limit < 30:
        raise ValueError("Maximum age must be at least 30 minutes")
    data = subprocess.check_output([
        "gh", "run", "list", "--repo", repo, "--workflow", workflow, "--branch", branch,
        "--event", "schedule", "--limit", "1", "--json", "createdAt,databaseId",
    ], timeout=30, encoding="utf-8")
    runs = json.loads(data)
    if runs and minutes_since(runs[0]["createdAt"], datetime.now(timezone.utc)) <= limit:
        return
    link = (f"https://github.com/{repo}/actions/runs/{int(runs[0]['databaseId'])}"
            if runs else f"https://github.com/{repo}/actions")
    body = (f"# 定时工作流可能漏跑\n\n最近 {limit} 分钟未找到预期的定时运行。\n\n"
            f"[查看运行记录]({link})\n\n检查触发配置、工作流启用状态和 GitHub 调度延迟。\n")
    Path(os.environ.get("GUARDIAN_REPORT", "incident.md")).write_text(body, encoding="utf-8")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
        out.write(body)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write("missed=true\n")


if __name__ == "__main__":
    main()
