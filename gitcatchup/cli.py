import argparse
import subprocess
import sys

from . import __version__, config
from .collect import GitError, collect
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
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    try:
        tests = _run_tests(args.test) if args.test else ""
        ctx = collect(n_commits=args.commits, max_diff_chars=cfg["max_diff_chars"], test_output=tests)
    except GitError as e:
        print(f"git catchup: {e}", file=sys.stderr)
        return 1

    # Facts come from git, not from the model.
    print(f"\n git catchup | branch: {ctx.branch}" + (f" (base: {ctx.base})" if ctx.base else ""))
    print(f" Last commit: {_ago(ctx.commit_age_days)}"
          + (f" | uncommitted edits: {_ago(ctx.work_age_days)}" if ctx.work_age_days is not None else ""))
    print(f" Uncommitted files: {len(ctx.changed_files)} | secrets redacted: {ctx.redactions}")
    for n in ctx.notes:
        print(f" note: {n}")
    print()

    prompt = build(ctx)
    if args.dry_run:
        print("----- PROMPT (this is everything the model sees) -----")
        print(prompt)
        return 0

    print(f" Reading the branch with {args.model} (locally)...\n", file=sys.stderr)
    try:
        print(generate(prompt, args.model, args.host, cfg["num_ctx"], cfg["timeout"]))
    except LLMError as e:
        print(f"git catchup: {e}", file=sys.stderr)
        return 2
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
