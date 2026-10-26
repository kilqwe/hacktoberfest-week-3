import argparse
import subprocess
import sys

from . import __version__, config
from .collect import GitError, collect
from .redact import is_sensitive_file
from .llm import LLMError, generate
from .prompt import build


def _ago(days: float | None) -> str:
    if days is None:
        return "n/a"
    if days < 1 / 24:
        return "just now"
    if days < 1:
        return f"{int(days * 24)}h ago"
    return f"{int(days)} day{'s' if int(days) != 1 else ''} ago"


def _run_tests(cmd: str) -> str:
    print(f"Running tests: {cmd}", file=sys.stderr)
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        return "(test command timed out after 180s)"
    out = (p.stdout + "\n" + p.stderr).strip().splitlines()
    return f"exit code {p.returncode}\n" + "\n".join(out[-40:])


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    cfg = config.load()
    ap = argparse.ArgumentParser(prog="git catchup",
                                 description="Catch up on where you left off on this branch.")
    ap.add_argument("--model", default=cfg["model"], help=f"Ollama model tag (default: {cfg['model']})")
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--commits", type=int, default=cfg["commits"], help="recent commits to include")
    ap.add_argument("--test", metavar="CMD", help='run a test command and include its output, e.g. --test "pytest -x"')
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would be sent to the model (after redaction) and exit")
    ap.add_argument("--out", metavar="FILE", help="also save the briefing to FILE as UTF-8 (avoids PowerShell redirect encoding issues)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    try:
        tests = _run_tests(args.test) if args.test else ""
        ctx = collect(n_commits=args.commits, max_diff_chars=cfg["max_diff_chars"], test_output=tests)
    except GitError as e:
        print(f"git catchup: {e}", file=sys.stderr)
        return 1

    buf: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        buf.append(text)

    # Everything factual is printed by Python straight from git. The model only
    # writes the short narrative at the end.
    emit(f"\n git catchup | branch: {ctx.branch}" + (f" (base: {ctx.base})" if ctx.base else ""))
    emit(f" Last commit: {_ago(ctx.commit_age_days)}"
         + (f" | uncommitted edits: {_ago(ctx.work_age_days)}" if ctx.work_age_days is not None else "")
         + f" | {ctx.total_commits} commits total")
    emit(f" Secrets redacted before prompting: {ctx.redactions}")
    for n in ctx.notes:
        emit(f" note: {n}")
    emit()
    emit(" Done so far (your latest commits):")
    for c in ctx.commit_subjects[:6]:
        emit(f"   - {c}")
    shown = [l for l in ctx.status.splitlines() if not is_sensitive_file(l[3:].strip())]
    if shown:
        emit()
        emit(f" Uncommitted ({len(shown)} files):")
        for l in shown[:8]:
            emit(f"   {l}")
    if ctx.todos:
        emit()
        emit(f" Open notes in your code ({len(ctx.todos)}):")
        for t in ctx.todos[:6]:
            emit(f"   - {t}")
        if len(ctx.todos) > 6:
            emit(f"   ... and {len(ctx.todos) - 6} more")
    for block in filter(None, ctx.notes_text.split("### ")):
        name, _, body = block.partition("\n")
        lines = [l.strip() for l in body.splitlines() if l.strip() and not l.startswith("...[truncated")]
        if lines:
            emit()
            emit(f" Your notes ({name.strip()}):")
            for l in lines[:8]:
                emit(f"   {l}")
    emit()
    emit(f" --- briefing, written locally by {args.model} ---")
    emit()

    prompt = build(ctx)
    if args.dry_run:
        print("----- PROMPT (this is everything the model sees) -----")
        print(prompt)
        return 0

    print(f" Reading the branch with {args.model} (locally)...\n", file=sys.stderr)
    try:
        out = generate(prompt, args.model, args.host, cfg["num_ctx"], cfg["timeout"])
        i = out.find("**")
        emit(out[i:] if i > 0 else out)
    except LLMError as e:
        print(f"git catchup: {e}", file=sys.stderr)
        return 2
    print()
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(buf) + "\n")
        print(f" saved to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
