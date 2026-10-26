import argparse
import subprocess
import sys

from . import __version__, config
from .collect import GitError, collect
from .llm import LLMError, generate
from .prompt import build
from .render import DIM, RESET, Renderer, enable_windows_ansi, wants_color
from .validate import FIELDS, SCHEMA, check, fallback, parse, with_feedback


def _run_tests(cmd: str) -> str:
    print(f"Running tests: {cmd}", file=sys.stderr)
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except subprocess.TimeoutExpired:
        return "(test command timed out after 180s)"
    out = (p.stdout + "\n" + p.stderr).strip().splitlines()
    return f"exit code {p.returncode}\n" + "\n".join(out[-40:])


def _briefing(prompt, ctx, args, cfg):
    """Ask the model, check the answer against git, retry once, then fall back to plain Python.
    Returns (final_fields, messages_for_stderr)."""
    msgs: list[str] = []

    def ask(p):
        return generate(p, args.model, args.host, cfg["num_ctx"], cfg["timeout"], schema=SCHEMA)

    text, used = ask(prompt)
    data = parse(text)
    problems = check(data, ctx.known_files)
    if problems:
        msgs.append(" [guard] first answer rejected: "
                    + "; ".join(f"{k} ({v})" for k, v in problems.items()) + ". Asking again.")
        text, used2 = ask(with_feedback(prompt, problems))
        used = max(used or 0, used2 or 0)
        data = parse(text)
        problems = check(data, ctx.known_files)
        if problems:
            msgs.append(" [guard] still wrong after retry, using plain git facts for: " + ", ".join(problems))
    fb = fallback(ctx)
    final = {k: (data[k].strip() if data and k not in problems else fb[k]) for k in FIELDS}
    if used and used >= 0.9 * cfg["num_ctx"]:
        msgs.append(f" [warning] prompt used {used} of {cfg['num_ctx']} tokens, so older context may have "
                    "been cut. Raise num_ctx in ~/.gitcatchup.toml.")
    return final, msgs


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    enable_windows_ansi()

    cfg = config.load()
    ap = argparse.ArgumentParser(prog="git catchup",
                                 description="Catch up on where you left off on this branch.")
    ap.add_argument("--model", default=cfg["model"], help=f"Ollama model tag (default: {cfg['model']})")
    ap.add_argument("--host", default=cfg["host"])
    ap.add_argument("--commits", type=int, default=cfg["commits"], help="recent commits to include")
    ap.add_argument("--test", metavar="CMD", help='run a test command and include its output, e.g. --test "pytest -x"')
    ap.add_argument("--dry-run", action="store_true",
                    help="print exactly what would be sent to the model (after redaction) and exit")
    ap.add_argument("--out", metavar="FILE", help="also save the briefing to FILE as plain UTF-8 text")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    try:
        tests = _run_tests(args.test) if args.test else ""
        ctx = collect(n_commits=args.commits, max_diff_chars=cfg["max_diff_chars"], test_output=tests)
    except GitError as e:
        print(f"git catchup: {e}", file=sys.stderr)
        return 1

    term = Renderer(fancy=wants_color(sys.stdout))   # colour + unicode in a terminal, ASCII when piped
    print(term.facts(ctx), flush=True)

    prompt = build(ctx)
    if args.dry_run:
        print("\n----- PROMPT (this is everything the model sees) -----")
        print(prompt)
        return 0

    spin = wants_color(sys.stderr)
    note = f" reading the branch with {args.model}, locally..."
    sys.stderr.write((DIM + note + RESET) if spin else note + "\n")
    sys.stderr.flush()
    try:
        final, msgs = _briefing(prompt, ctx, args, cfg)
    except LLMError as e:
        if spin:
            sys.stderr.write("\r\033[K")
        print(f"git catchup: {e}", file=sys.stderr)
        return 2
    if spin:
        sys.stderr.write("\r\033[K")
    for m in msgs:
        print(m, file=sys.stderr)

    print(term.briefing(final))
    if args.out:
        plain = Renderer(fancy=False)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(plain.facts(ctx).lstrip("\n") + "\n" + plain.briefing(final))
        print(f" saved to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())