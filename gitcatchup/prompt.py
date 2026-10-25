from .collect import Context

TEMPLATE = """You are helping a developer resume work on a git branch after time away.
Using ONLY the context below, write a short briefing with exactly these sections:

**Where you left off** (2 sentences)
**State of the work** (up to 3 bullets: done / in progress / broken)
**Next step** (one concrete action)

Rules: if something is unclear from the context, say so instead of guessing.
Do not invent file names, functions, or test results. Do not repeat the context back.

Branch: {branch}
Recent commits (newest first, with files touched):
{commits}

Uncommitted changes (git status --short):
{status}

TODO/FIXME lines added in uncommitted work:
{todos}

Last test output:
{tests}

Diff of uncommitted work (may be truncated):
{diff}
"""


def build(ctx: Context) -> str:
    return TEMPLATE.format(
        branch=ctx.branch,
        commits=ctx.commits or "(none)",
        status=ctx.status or "(working tree clean)",
        todos="\n".join(ctx.todos) or "(none)",
        tests=ctx.test_output or "(not provided)",
        diff=ctx.diff or "(no uncommitted changes)",
    )
