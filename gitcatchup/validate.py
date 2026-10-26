import json
import re

from .redact import is_sensitive_file

FIELDS = ("project", "left_off", "next_step")

SCHEMA = {
    "type": "object",
    "properties": {f: {"type": "string"} for f in FIELDS},
    "required": list(FIELDS),
}

SECRET = re.compile(r"(?i)api[\s_-]?key|secret|passw(?:or)?d|\.env\b|redact|credential")
FILE_EXTS = {"py", "js", "ts", "tsx", "jsx", "json", "toml", "yaml", "yml", "md", "txt", "html",
             "css", "java", "go", "rs", "c", "cpp", "h", "rb", "php", "sh", "sql", "ini", "cfg", "lock"}


def parse(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        return None
    try:
        data = json.loads(t[i:j + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def _unknown_files(text: str, known: set[str]) -> list[str]:
    bad = []
    for tok in re.findall(r"`([^`\s]+)`", text):
        name = re.sub(r":\d+$", "", tok).replace("\\", "/")
        if name.rsplit(".", 1)[-1].lower() not in FILE_EXTS or "." not in name:
            continue
        if name not in known and name.rsplit("/", 1)[-1] not in known:
            bad.append(name)
    return bad


def check(data: dict | None, known_files: set[str]) -> dict[str, str]:
    """Return {field: problem} for every field that fails. Empty dict means all good."""
    if data is None:
        return {f: "answer was not valid JSON" for f in FIELDS}
    known = set(known_files) | {k.rsplit("/", 1)[-1] for k in known_files}
    problems: dict[str, str] = {}
    for f in FIELDS:
        v = data.get(f)
        if not isinstance(v, str) or not v.strip():
            problems[f] = "missing or empty"
            continue
        if SECRET.search(v):
            problems[f] = "mentions secrets, keys or .env files"
            continue
        unknown = _unknown_files(v, known)
        if unknown:
            problems[f] = f"mentions files that do not exist: {', '.join(unknown)}"
            continue
        n = _sentences(v)
        if f == "project" and (len(v) > 220 or n > 2):
            problems[f] = "too long"
        elif f == "left_off" and n > 3:
            problems[f] = "should be 2 sentences"
        elif f == "next_step" and (v.strip().endswith("?") or n > 2 or len(v) > 300):
            problems[f] = "must be one action, not a question or a list"
    return problems


def with_feedback(prompt: str, problems: dict[str, str]) -> str:
    lines = "; ".join(f"{k}: {v}" for k, v in problems.items())
    return (prompt + "\nYour previous answer was rejected by an automatic check. Problems: "
            + lines + ". Answer again as JSON and fix exactly these problems.\n")


def fallback(ctx) -> dict[str, str]:
    """Plain-Python answers, used for any field the model gets wrong twice."""
    files = [l[3:].strip() for l in ctx.status.splitlines() if not is_sensitive_file(l[3:].strip())]
    if files:
        left = "Your last uncommitted changes were in: " + ", ".join(f"`{f}`" for f in files[:5]) + "."
    elif ctx.commit_subjects:
        left = "Your latest commit was: " + ctx.commit_subjects[0].split("  ", 1)[-1] + "."
    else:
        left = "No recent activity found."
    return {
        "project": "Unclear.",
        "left_off": left,
        "next_step": ("Start with: " + ctx.start_here) if ctx.start_here else "Review your latest commit and decide what comes next.",
    }
