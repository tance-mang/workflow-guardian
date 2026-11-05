"""Optional AI triage using an allowlisted summary of failure symptoms."""
import json
import os
import re
from urllib.request import Request, urlopen

SIGNALS = {
    "auth": r"HTTP (?:Error )?(?:401|403)\b",
    "upstream_5xx": r"HTTP (?:Error )?5\d\d\b",
    "dependency": r"No matching distribution found|ModuleNotFoundError",
    "configuration": r"ValueError|invalid configuration",
    "git_conflict": r"non-fast-forward|HTTP (?:Error )?409\b",
}


def suggestion(conclusion, logs, previous_failures=None):
    key = os.environ.get("GUARDIAN_AI_KEY")
    model = os.environ.get("GUARDIAN_AI_MODEL")
    if not key or not model:
        return ""
    signals = [name for name, pattern in SIGNALS.items() if re.search(pattern, logs, re.I)]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "用中文给出一条简短人工排查建议。只按信号提假设，不猜已发布状态，不输出命令或链接。"},
            {"role": "user", "content": json.dumps({"conclusion": conclusion, "signals": signals, "recent_failure_count": previous_failures})},
        ],
        "max_completion_tokens": 300,
    }
    req = Request("https://api.openai.com/v1/chat/completions",
                  data=json.dumps(payload).encode("utf-8"),
                  headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=15) as response:
            content = json.loads(response.read(65536))["choices"][0]["message"]["content"]
        return " ".join(content.split())[:240] if isinstance(content, str) else ""
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return ""
