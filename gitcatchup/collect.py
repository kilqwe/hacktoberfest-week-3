import os
import re
import subprocess
import time
from dataclasses import dataclass, field

from .redact import is_sensitive_file, redact

SKIP_DIFF = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|poetry\.lock|pnpm-lock\.yaml|Cargo\.lock)$")


class GitError(Exception):
    pass


def git(*args: str, cwd: str | None = None, check: bool = True) -> str:
    p = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True,
        encoding="utf-8", errors="replace",
    )
    if check and p.returncode != 0:
        raise GitError(p.stderr.strip() or f"git {' '.join(args)} failed")
    return p.stdout.strip("\n")


@dataclass
class Context:
    branch: str
    base: str | None
    commit_age_days: float | None
    work_age_days: float | None
    commits: str
    status: str
    changed_files: list[str]
    diff: str
    todos: list[str]
    test_output: str = ""
    redactions: int = 0
    notes: list[str] = field(default_factory=list)


def _find_base(cwd) -> str | None:
    for cand in ("main", "master", "origin/main", "origin/master"):
        if git("rev-parse", "--verify", "--quiet", cand, cwd=cwd, check=False):
            return cand
    return None


def _split_diff(diff: str) -> list[tuple[str, str]]:
    chunks = []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        if not part.strip():
            continue
        m = re.match(r"diff --git a/(.+?) b/(.+)", part)
        chunks.append((m.group(2) if m else "?", part))
    return chunks


def _budget_diff(diff: str, budget: int, notes: list[str]) -> str:
    chunks = [(f, c) for f, c in _split_diff(diff)
              if not SKIP_DIFF.search(f) and not is_sensitive_file(f)]
    if not chunks:
        return ""
    per_file = max(500, budget // len(chunks))
    out, truncated = [], 0
    for _, chunk in chunks:
        if len(chunk) > per_file:
            chunk = chunk[:per_file] + "\n... [truncated]\n"
            truncated += 1
        out.append(chunk)
    if truncated:
        notes.append(f"{truncated} file diff(s) truncated to fit the model's context")
    return "".join(out)[: budget + 2000]


def collect(cwd: str | None = None, n_commits: int = 8, max_diff_chars: int = 6000,
            test_output: str = "") -> Context:
    try:
        git("rev-parse", "--is-inside-work-tree", cwd=cwd)
    except GitError:
        raise GitError("Not inside a git repository.")

    has_commits = bool(git("rev-parse", "--verify", "--quiet", "HEAD", cwd=cwd, check=False))
    if not has_commits:
        raise GitError("This repository has no commits yet, so there's nothing to catch up on.")

    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)
    base = _find_base(cwd)
    notes: list[str] = []

    # Time away: last commit vs. newest mtime among uncommitted files.
    now = time.time()
    commit_ts = int(git("log", "-1", "--format=%ct", cwd=cwd))
    commit_age = (now - commit_ts) / 86400

    status = git("status", "--short", cwd=cwd)
    changed = []
    for line in status.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        changed.append(path)
    root = git("rev-parse", "--show-toplevel", cwd=cwd)
    mtimes = []
    for p in changed:
        fp = os.path.join(root, p)
        if os.path.isfile(fp):
            mtimes.append(os.path.getmtime(fp))
    work_age = (now - max(mtimes)) / 86400 if mtimes else None

    # Commits: on a feature branch show what's ahead of base; otherwise the latest N.
    fmt = "--pretty=format:%h %ad %s"
    if base and branch not in (base, base.split("/")[-1]):
        rng = f"{base}..HEAD"
        commits = git("log", rng, f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)
        if not commits:
            commits = git("log", f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)
            notes.append("branch has no commits ahead of base; showing latest commits")
    else:
        commits = git("log", f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)

    raw_diff = git("diff", "HEAD", cwd=cwd)
    diff = _budget_diff(raw_diff, max_diff_chars, notes)

    todos = []
    for line in raw_diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and re.search(r"\b(TODO|FIXME|XXX|HACK)\b", line):
            todos.append(line[1:].strip())

    # Redact everything that will leave this module.
    total = 0
    def clean(t):
        nonlocal total
        t, n = redact(t)
        total += n
        return t

    ctx = Context(
        branch=branch, base=base,
        commit_age_days=commit_age, work_age_days=work_age,
        commits=clean(commits), status=status, changed_files=changed,
        diff=clean(diff), todos=[clean(t) for t in todos[:10]],
        test_output=clean(test_output), notes=notes,
    )
    ctx.redactions = total
    return ctx
