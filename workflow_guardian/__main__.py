"""Build a public-safe incident report from a trusted GitHub run."""
import argparse
import json
import os
import re
import smtplib
import ssl
import subprocess
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote
from .ai import suggestion
from .schedule import main as check_schedule

RULES = (
    ("github_permission", r"Resource not accessible by integration|Write access to repository not granted", "GitHub 拒绝写入", "核对目标仓库、令牌的 Contents 写权限和分支规则。"),
    ("dependency", r"No matching distribution found|ERESOLVE unable to resolve dependency tree|ModuleNotFoundError", "依赖安装或导入失败", "检查依赖版本、锁文件和运行环境。"),
    ("build", r"error TS\d+|compilation failed|BUILD FAILED", "构建或编译失败", "定位首条编译错误，核对工具链版本。"),
    ("credentials", r"HTTP (?:Error )?401\b|invalid_api_key|Authentication failed", "凭据疑似无效", "核对凭据是否存在、是否过期及使用范围。"),
    ("upstream", r"HTTP (?:Error )?5(?:00|02|03|04)\b", "上游服务疑似异常", "查询服务状态，确认是否已执行后再重试。"),
    ("simulation", r"GUARDIAN_DRILL", "演练注入了预期故障", "确认报告产物存在，无需重跑发布。"),
    ("rate_limit", r"HTTP(?: Error)? 429\b|rate_limit_exceeded", "服务疑似限流", "查看服务配额和重试间隔，确认后再重跑。"),
    ("network", r"TimeoutError|timed out|Temporary failure in name resolution", "网络请求或任务疑似超时", "检查服务状态和网络，再决定是否重跑。"),
)

BLOG_RULES = (
    ("configuration", r"\b(?:BLOG_TOKEN|AI_API_KEY) is required\b", "缺少配置凭据", "检查对应仓库 Secret，确认后再重跑。"),
    ("model_configuration", r"Configure AI_API_KEY and writer_model/reviewer_model", "模型配置不完整", "核对模型名称和 Actions 凭据。"),
)

def diagnose(conclusion, logs):
    if conclusion == "timed_out":
        return "timeout", "GitHub 标记运行超时", "检查各步骤耗时、外部请求与任务超时设置。"
    for code, pattern, reason, action in (*RULES, *BLOG_RULES) if os.environ.get("GUARDIAN_PROFILE") == "blog" else RULES:
        if re.search(pattern, logs, re.I):
            return code, reason, action
    return "unknown", "证据不足，需人工排查", "从原运行页查看第一个失败步骤，并检查是否已有发布结果。"


def report(repo, run, logs, logs_available):
    run_id = int(run["id"])
    attempt = int(run["run_attempt"])
    conclusion = run["conclusion"]
    if conclusion not in {"failure", "timed_out", "startup_failure", "action_required", "cancelled", "stale"}:
        raise ValueError("Unsupported incident conclusion")
    code, reason, action = diagnose(conclusion, logs)
    return f"""# 自动化故障报告 · {run_id}/{attempt}

| 字段 | 结果 |
| --- | --- |
| GitHub 运行结果 | `{conclusion}` |
| 诊断规则 | `{code}` |
| 失败日志 | {'已用于匹配规则' if logs_available else '暂不可用，按运行状态诊断'} |
| 原运行 | [查看第 {attempt} 次尝试](https://github.com/{repo}/actions/runs/{run_id}/attempts/{attempt}) |

**初步判断**　{reason}

**影响范围**　该次运行异常结束。外部操作是否已生效仍需核对。

**处理建议**　{action} 重跑前先核对目标端，避免重复执行外部操作。
"""


def send_email(body):
    msg = EmailMessage()
    msg["Subject"] = "Workflow Guardian · 自动化故障"
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = os.environ["SMTP_TO"]
    msg.set_content(body)
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], 465, context=ssl.create_default_context(), timeout=20) as smtp:
        smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def prior_failures(repo, run):
    endpoint = (f"repos/{repo}/actions/workflows/{int(run['workflow_id'])}/runs"
                f"?branch={quote(run['head_branch'], safe='')}&status=completed&per_page=11")
    try:
        result = subprocess.check_output(["gh", "api", endpoint], timeout=10, encoding="utf-8",
                                         stderr=subprocess.DEVNULL)
        previous = [item for item in json.loads(result)["workflow_runs"]
                    if item["id"] != run["id"]][:10]
        return sum(item["conclusion"] in {"failure", "timed_out", "startup_failure"}
                   for item in previous)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None


def github_report():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    run = event["workflow_run"]
    repo = os.environ["GITHUB_REPOSITORY"]
    if (run["head_repository"]["full_name"] != repo
            or run["head_branch"] != event["repository"]["default_branch"]):
        raise ValueError("Only runs from the same repository and its default branch are trusted")
    try:
        result = subprocess.run(
            ["gh", "run", "view", str(int(run["id"])), "--repo", repo,
             "--attempt", str(int(run["run_attempt"])), "--log-failed"],
            capture_output=True, timeout=60, encoding="utf-8", errors="replace",
        )
        logs = result.stdout if result.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        logs = ""
    body = report(repo, run, logs, bool(logs.strip()))
    if (diagnose(run["conclusion"], logs)[0] == "unknown"
            and os.environ.get("GUARDIAN_AI_KEY") and os.environ.get("GUARDIAN_AI_MODEL")):
        history = prior_failures(repo, run)
        if history is not None:
            body += f"\n**近期记录**　同一工作流最近最多 10 次其他运行中有 {history} 次异常。\n"
        extra = suggestion(run["conclusion"], logs, history)
        if extra:
            text = re.sub(r"[^\w\s，。；：、？！（）-]", " ", extra)
            body += f"\n**AI 排查建议（待验证）**　{text}\n"
    Path(os.environ.get("GUARDIAN_REPORT", "incident.md")).write_text(body, encoding="utf-8")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(body)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
        out.write(f"incident=incident-{int(run['id'])}-{int(run['run_attempt'])}\n")


def mail(incident):
    # A successful delivery receipt is stored as an Actions artifact by the Action.
    # Never log SMTP provider responses, which can include account details.
    if incident:
        repo = os.environ["GITHUB_REPOSITORY"]
        endpoint = f"repos/{repo}/actions/artifacts?name={incident}-email&per_page=100"
        raw = subprocess.check_output(["gh", "api", endpoint], encoding="utf-8", timeout=30)
        if any(not artifact["expired"] for artifact in json.loads(raw)["artifacts"]):
            return
    try:
        send_email(Path(os.environ.get("GUARDIAN_REPORT", "incident.md")).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        raise SystemExit("SMTP delivery failed; check the configured secrets and provider")
    if incident:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("delivered=true\n")


def main():
    parser = argparse.ArgumentParser(prog="workflow-guardian")
    sub = parser.add_subparsers(dest="mode", required=True)
    analyze = sub.add_parser("analyze", help="Analyze a local log without transmitting it")
    analyze.add_argument("log", type=Path)
    sub.add_parser("github", help="Diagnose the workflow_run event")
    sub.add_parser("schedule", help="Check the expected scheduled run")
    email = sub.add_parser("mail", help="Send an existing report")
    email.add_argument("--incident")
    args = parser.parse_args()
    if args.mode == "analyze":
        with args.log.open(encoding="utf-8", errors="replace") as log:
            code, reason, action = diagnose("failure", log.read(2_000_000))
        print(f"# Workflow Guardian\n\n- 分类：{code}\n- 初步判断：{reason}\n- 处理建议：{action}")
    elif args.mode == "github":
        github_report()
    elif args.mode == "schedule":
        check_schedule()
    else:
        mail(args.incident)


if __name__ == "__main__":
    main()
