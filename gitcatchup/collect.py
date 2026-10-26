"""Gather facts from git. Everything factual comes from here, not from the model."""
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
    readme: str = ""
    notes_text: str = ""
    notes_files: list[str] = field(default_factory=list)
    total_commits: int = 0
    commit_subjects: list[str] = field(default_factory=list)
    start_here: str = ""
    known_files: set[str] = field(default_factory=set)


NOTE_NAMES = re.compile(r"(?i)^(todos?|notes?|roadmap|ideas?|plan|backlog|wishlist)(\.[a-z]+)?$")
README_NAME = re.compile(r"(?i)^readme(\.[a-z]+)?$")


def _read(path: str, limit: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            t = f.read(limit + 1)
    except OSError:
        return ""
    return t[:limit] + ("\n...[truncated]" if len(t) > limit else "")


def _project_docs(root: str) -> tuple[str, str, list[str]]:
    """README excerpt + any notes/todo/roadmap files in the repo root."""
    readme, notes, names = "", [], []
    budget = 3000
    for name in sorted(os.listdir(root)):
        fp = os.path.join(root, name)
        if not os.path.isfile(fp) or is_sensitive_file(name):
            continue
        if README_NAME.match(name) and not readme:
            readme = _read(fp, 1500)
        elif NOTE_NAMES.match(name) and budget > 0:
            text = _read(fp, min(2000, budget))
            budget -= len(text)
            notes.append(f"### {name}\n{text}")
            names.append(name)
    return readme, "\n\n".join(notes), names


def _repo_todos(root: str) -> list[str]:
    """TODO/FIXME lines across the whole repo (tracked + untracked, committed or not)."""
    out = git("grep", "-n", "-I", "-w", "--untracked",
              "-e", "TODO", "-e", "FIXME", "-e", "XXX", "-e", "HACK", cwd=root, check=False)
    found = []
    for line in out.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, lineno, text = parts
        base = os.path.basename(path)
        if (NOTE_NAMES.match(base) or README_NAME.match(base) or SKIP_DIFF.search(path)
                or is_sensitive_file(path)):
            continue
        found.append(f"{path}:{lineno}: {text.strip()[:160]}")
    return found[:15]


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
    rng_args: list[str] = []
    fmt = "--pretty=format:%h %ad %s"
    if base and branch not in (base, base.split("/")[-1]):
        rng = f"{base}..HEAD"
        commits = git("log", rng, f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)
        rng_args = [rng]
        if not commits:
            rng_args = []
            commits = git("log", f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)
            notes.append("branch has no commits ahead of base; showing latest commits")
    else:
        commits = git("log", f"-n{n_commits}", fmt, "--date=short", "--name-only", cwd=cwd)

    subjects = git("log", *rng_args, f"-n{n_commits}", "--pretty=format:%ad  %s",
                   "--date=short", cwd=cwd).splitlines()
    raw_diff = git("diff", "HEAD", cwd=cwd)
    diff = _budget_diff(raw_diff, max_diff_chars, notes)

    todos = _repo_todos(root)
    # TODOs in files you were just editing come first.
    changed_set = {c.replace("\\", "/") for c in changed}
    todos.sort(key=lambda t: t.split(":", 1)[0] not in changed_set)
    readme, notes_text, notes_files = _project_docs(root)
    total_commits = int(git("rev-list", "--count", "HEAD", cwd=cwd))

    # Redact everything that will leave this module.
    total = 0
    def clean(t):
        nonlocal total
        t, n = redact(t)
        total += n
        # The model never sees lines that held a secret, so it cannot talk about them.
        return re.sub(r"(?m)^.*\[REDACTED.*$", "[line omitted]", t)

    ctx = Context(
        branch=branch, base=base,
        commit_age_days=commit_age, work_age_days=work_age,
        commits=clean(commits), status=status, changed_files=changed,
        diff=clean(diff), todos=[clean(t) for t in todos],
        test_output=clean(test_output), notes=notes,
        readme=clean(readme), notes_text=clean(notes_text),
        notes_files=notes_files, total_commits=total_commits,
        commit_subjects=[clean(x) for x in subjects],
    )
    ctx.redactions = total
    ctx.known_files = {f.replace("\\", "/") for f in
                       git("ls-files", "--cached", "--others", "--exclude-standard", cwd=root).splitlines()}
    # Priority: failing tests > TODO/FIXME (edited files first) > first line of a notes file.
    if test_output and not test_output.startswith("exit code 0"):
        ctx.start_here = "make the failing tests pass (see TEST OUTPUT)"
    elif ctx.todos:
        ctx.start_here = ctx.todos[0]
    else:
        for line in ctx.notes_text.splitlines():
            line = line.strip().lstrip("-*\u2022 ").strip()
            if line and not line.startswith("###") and not line.startswith("...[truncated"):
                ctx.start_here = f"idea from your notes: {line}"
                break
    return ctx
