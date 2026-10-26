from .collect import Context
from .redact import is_sensitive_file

RULES = """Rules: address the developer as "you". Put file names in backticks. Use only the context above. Comment lines such as # TODO or # FIXME are reminders of work that is NOT done yet, never finished work. If something is unclear, say so instead of guessing. Do not invent file names, functions, or results, and do not suggest features that are not written in the context. Do not mention secrets, API keys, or passwords."""


def _instructions(has_uncommitted: bool, has_start: bool) -> str:
    # Lists (done / open / notes) and the starting item are chosen by Python from git.
    # The model only writes three short pieces, and only sees instructions that apply.
    left = ("**Where you left off**: exactly 2 sentences about the UNCOMMITTED WORK: which files "
            "you were editing and what changed in them."
            if has_uncommitted else
            "**Where you left off**: exactly 2 sentences about the most recent commit(s).")
    nxt = ("**Next step**: ONE action in one sentence that carries out the START HERE item. "
           "Phrase it as an action, not a question."
           if has_start else
           "**Next step**: ONE action in one sentence, based on the uncommitted work or the latest commit.")
    return "\n".join([
        "Reply with a JSON object with exactly these 3 string fields and nothing else:",
        "",
        '"project": 1 sentence from the README or commit messages. If neither says, write: Unclear.',
        '"left_off": ' + left.split(": ", 1)[1],
        '"next_step": ' + nxt.split(": ", 1)[1],
    ]) + "\n\n" + RULES


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
    if ctx.start_here:
        parts.append("START HERE :\n" + ctx.start_here)
    instr = _instructions(has_uncommitted, bool(ctx.start_here))
    return "\n\n".join(parts) + "\n\n" + instr + "\n"
