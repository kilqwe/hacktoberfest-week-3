from .collect import Context
from .redact import is_sensitive_file

RULES = """Rules: address the developer as "you". Start directly with the first heading, with no introduction or closing remarks. Use only the context above. If something is unclear, say so instead of guessing. Do not invent file names, functions, or results, and do not suggest features that are not written in the context. Do not mention secrets, API keys, or passwords."""


def _instructions(has_uncommitted: bool, has_notes: bool, has_tests: bool) -> str:
    # The lists (done / open / notes) are printed by Python from git. The model only
    # writes three short pieces, and only sees instructions that apply.
    left = ("**Where you left off**: exactly 2 sentences about the UNCOMMITTED WORK: which files "
            "you were editing and what you were changing."
            if has_uncommitted else
            "**Where you left off**: exactly 2 sentences about the most recent commit(s).")
    order = ["the uncommitted work"] if has_uncommitted else []
    order.append("a TODO/FIXME line")
    if has_tests:
        order.insert(0, "a failing test")
    if has_notes:
        order.append("an idea from the NOTES files")
    lines = [
        "Write a short briefing for the developer using ONLY the context above, with exactly these 3 sections and no others:",
        "",
        "**What this project is**: 1 sentence from the README or commit messages. If neither says, write: Unclear.",
        left,
        "**Next step**: ONE action in one sentence, chosen from the first of these that applies: "
        + ", then ".join(order) + ". It must be something written in the context.",
    ]
    return "\n".join(lines) + "\n\n" + RULES


def build(ctx: Context) -> str:
    status = "\n".join(l for l in ctx.status.splitlines()
                       if not is_sensitive_file(l[3:].strip()))
    has_uncommitted = bool(status.strip())
    parts = []
    if ctx.readme:
        parts.append("README (start of file):\n" + ctx.readme)
    if ctx.notes_text:
        parts.append("NOTES FILES (the developer's own notes and ideas):\n" + ctx.notes_text)
    parts.append(f"HISTORY\nBranch: {ctx.branch} ({ctx.total_commits} commits in total)\n"
                 f"Recent commits (newest first, with files touched):\n{ctx.commits or '(none)'}")
    if has_uncommitted:
        parts.append("UNCOMMITTED WORK (this is where they stopped)\nFiles changed:\n" + status
                     + "\n\nDiff (may be truncated):\n" + (ctx.diff or "(none)"))
    parts.append("TODO/FIXME lines found in the code:\n" + ("\n".join(ctx.todos) or "(none)"))
    if ctx.test_output:
        parts.append("TEST OUTPUT:\n" + ctx.test_output)
    instr = _instructions(has_uncommitted, bool(ctx.notes_text), bool(ctx.test_output))
    return "\n\n".join(parts) + "\n\n" + instr + "\n"
