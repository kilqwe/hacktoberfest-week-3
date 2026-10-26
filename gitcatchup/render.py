import os
import re
import shutil
import textwrap
from datetime import datetime

from .redact import is_sensitive_file

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
CYAN, YELLOW, RED, GREEN, MAGENTA = "\033[36m", "\033[33m", "\033[31m", "\033[32m", "\033[35m"

STATUS_COLORS = {"M": YELLOW, "A": GREEN, "D": RED, "R": CYAN, "?": DIM}
TAG_COLORS = {"TODO": YELLOW, "FIXME": RED, "XXX": RED, "HACK": MAGENTA}
TODO_RE = re.compile(r"^(.+?):(\d+): (.*)$")
TAG_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
LOC_COL = 18          # indent of the text column in the OPEN section


def enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, mode.value | 0x0004)   # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def wants_color(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return stream.isatty() and os.environ.get("TERM") != "dumb"


def ago(days: float | None) -> str:
    if days is None:
        return "n/a"
    if days < 1 / 24:
        return "just now"
    if days < 1:
        return f"{int(days * 24)}h ago"
    return f"{int(days)} day{'s' if int(days) != 1 else ''} ago"


class Renderer:
    def __init__(self, fancy: bool, cols: int | None = None):
        self.fancy = fancy                      # colour + unicode; False = plain ASCII
        cols = cols or shutil.get_terminal_size((90, 20)).columns
        self.width = max(56, min(cols, 100)) - 2
        self.dot, self.sep, self.arrow, self.bullet, self.rule = (
            ("●", "·", "→", "•", "─") if fancy else ("*", "|", "->", "-", "-"))

    # helpers 
    def c(self, text: str, *styles: str) -> str:
        return "".join(styles) + text + RESET if self.fancy and styles else text

    def h(self, title: str, extra: str = "") -> str:
        return " " + self.c(title, BOLD, CYAN) + (" " + self.c(extra, DIM) if extra else "")

    def hi(self, line: str) -> str:
        """Highlight `backticked` names (colour mode only; plain mode keeps the backticks)."""
        if not self.fancy:
            return line
        return re.sub(r"`([^`]+)`", lambda m: self.c(m.group(1), CYAN), line)

    def para(self, text: str, first: str = "   ", rest: str = "   ") -> list[str]:
        lines = textwrap.wrap(" ".join(text.split()), width=self.width,
                              initial_indent=first, subsequent_indent=rest) or [first]
        return [self.hi(l) for l in lines]

    def _date(self, d: str) -> str:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            s = dt.strftime("%b %d") if dt.year == datetime.now().year else dt.strftime("%b %d %y")
        except ValueError:
            s = d
        return s

    # sections printed from git facts 
    def facts(self, ctx) -> str:
        L: list[str] = []
        title = f" {self.c(self.dot, CYAN)} {self.c(ctx.branch, BOLD)}"
        if ctx.base and ctx.branch != ctx.base.split("/")[-1]:
            title += self.c(f"  from {ctx.base}", DIM)
        bits = [f"last commit {ago(ctx.commit_age_days)}"]
        if ctx.work_age_days is not None:
            bits.append(f"edits {ago(ctx.work_age_days)}")
        bits.append(f"{ctx.total_commits} commit{'s' if ctx.total_commits != 1 else ''}")
        L += ["", title, "   " + self.c(f" {self.sep} ".join(bits), DIM)]
        if ctx.redactions:
            n = ctx.redactions
            L.append("   " + self.c(f"{n} secret{'s' if n != 1 else ''} hidden from the model", DIM))
        for n in ctx.notes:
            L.append("   " + self.c(n, DIM))

        if ctx.commit_subjects:
            L += ["", self.h("DONE SO FAR")]
            rows = [(self._date(d), subj or d) for d, _, subj in
                    (x.partition("  ") for x in ctx.commit_subjects[:5])]
            w = max(len(r[0]) for r in rows)
            for label, subj in rows:
                wrapped = textwrap.wrap(subj, width=self.width - w - 5) or [""]
                L.append(f"   {self.c(label.ljust(w), DIM)}  {wrapped[0]}")
                L += [" " * (w + 5) + x for x in wrapped[1:]]

        shown = [l for l in ctx.status.splitlines() if not is_sensitive_file(l[3:].strip())]
        if shown:
            L += ["", self.h("UNCOMMITTED", f"{len(shown)} file{'s' if len(shown) != 1 else ''}")]
            for l in shown[:8]:
                code, path = (l[:2].strip() or "?"), l[3:]
                col = STATUS_COLORS.get(code[0], DIM)
                L.append(f"   {self.c(code.ljust(2), BOLD, col)} {path}")
            if len(shown) > 8:
                L.append("   " + self.c(f"+ {len(shown) - 8} more", DIM))

        if ctx.todos:
            n = len(ctx.todos)
            L += ["", self.h("OPEN", f"{n} note{'s' if n != 1 else ''} in your code")]
            groups: dict[str, list] = {}
            other: list[str] = []
            for t in ctx.todos[:6]:
                m = TODO_RE.match(t)
                if not m:
                    other.append(t)
                    continue
                path, line, body = m.groups()
                tm = TAG_RE.search(body)
                tag = tm.group(1) if tm else "NOTE"
                text = body[tm.end():].lstrip(":- ").strip() if tm else body
                text = re.sub(r"\s*(\*/|-->)\s*$", "", text)
                groups.setdefault(path, []).append((line, tag, text))
            for path, items in groups.items():
                L.append("   " + self.c(path, BOLD))
                for line, tag, text in items:
                    wrapped = [textwrap.shorten(text, width=self.width - LOC_COL, placeholder="...")]
                    head = (f"     {self.c((':' + line).ljust(5), DIM)} "
                            f"{self.c(tag.ljust(5), BOLD, TAG_COLORS.get(tag, MAGENTA))}  ")
                    L.append(head + wrapped[0])
                    L += [" " * LOC_COL + w for w in wrapped[1:]]
            for t in other:
                L.append("   " + self.c(t, DIM))
            if n > 6:
                L.append("   " + self.c(f"+ {n - 6} more", DIM))

        for block in filter(None, ctx.notes_text.split("### ")):
            name, _, body = block.partition("\n")
            lines = [re.sub(r"^[-*\u2022]\s*", "", l.strip()) for l in body.splitlines()
                     if l.strip() and not l.startswith("...[truncated")]
            if lines:
                L += ["", self.h("NOTES", name.strip())]
                for l in lines[:6]:
                    b = f"   {self.bullet} "
                    L += self.para(l, first=b, rest=" " * len(b))
        return "\n".join(L)

    # the model's three short items 
    def briefing(self, final: dict) -> str:
        L = ["", " " + self.c(self.rule * (self.width - 1), DIM)]
        proj = final["project"].strip()
        if not proj.lower().startswith("unclear"):
            L += ["", self.h("ABOUT")] + self.para(proj)
        L += ["", self.h("WHERE YOU LEFT OFF")] + self.para(final["left_off"])
        first = f"   {self.arrow} "
        step = self.para(final["next_step"], first=first, rest=" " * len(first))
        step[0] = step[0].replace(self.arrow, self.c(self.arrow, BOLD, GREEN), 1)
        L += ["", self.h("NEXT STEP")] + step + [""]
        return "\n".join(L)