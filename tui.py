"""Tiny terminal UI for the setup wizard: checkboxes, single choice, text, yes/no.

Uses `questionary` (arrow keys + space to tick) when it's installed and the terminal is
interactive; otherwise falls back to numbered lists (type numbers to toggle), which works
everywhere — plain SSH, Windows cmd, piped input.
"""

import sys

try:
    import questionary
    from questionary import Choice, Separator
except ImportError:  # fallback UI below
    questionary = None

FANCY = questionary is not None and sys.stdin.isatty() and sys.stdout.isatty()

# a group header inside a checkbox list: ("---", "Hardware & RF")
SEP = "---"

LANG = "en"  # set by the wizard after the language question
_S = {
    "en": {"toggle": "Numbers to toggle (e.g. 1 3 5), a = all, n = none, Enter = done",
           "number": "Number", "default": "default", "yn": ("Y/n", "y/N"), "space": "Space = tick, Enter = done"},
    "he": {"toggle": "מספרים לסימון/ביטול (למשל 1 3 5), a = הכול, n = כלום, Enter = סיום",
           "number": "מספר", "default": "ברירת מחדל", "yn": ("כן/לא", "כן/לא"), "space": "רווח = סימון, Enter = סיום"},
}


def _s(key):
    return _S.get(LANG, _S["en"])[key]


class Cancelled(Exception):
    pass


def _done(value):
    if value is None:  # Ctrl-C in questionary
        raise Cancelled()
    return value


def checkbox(message: str, items: list[tuple], hint: str = "") -> list:
    """items: (value, label, checked) or (SEP, header). Returns the ticked values."""
    if FANCY:
        choices = [Separator(f"── {it[1]} ──") if it[0] == SEP else Choice(it[1], value=it[0], checked=it[2])
                   for it in items]
        return _done(questionary.checkbox(message, choices=choices, instruction=hint or _s("space")).ask())

    rows = [it for it in items if it[0] != SEP]
    ticked = {it[0] for it in rows if it[2]}
    while True:
        print(f"\n{message}")
        n = 0
        for it in items:
            if it[0] == SEP:
                print(f"   ── {it[1]} ──")
                continue
            n += 1
            print(f"  {n:2d}. [{'x' if it[0] in ticked else ' '}] {it[1]}")
        answer = input(f"  {hint or _s('toggle')}: ").strip().lower()
        if not answer:
            return [it[0] for it in rows if it[0] in ticked]
        if answer == "a":
            ticked = {it[0] for it in rows}
            continue
        if answer == "n":
            ticked = set()
            continue
        for tok in answer.replace(",", " ").split():
            if tok.isdigit() and 1 <= int(tok) <= len(rows):
                ticked ^= {rows[int(tok) - 1][0]}


def select(message: str, items: list[tuple], default=None):
    """items: (value, label). Returns the chosen value."""
    if FANCY:
        choices = [Choice(lbl, value=v) for v, lbl in items]
        return _done(questionary.select(message, choices=choices,
                                        default=next((c for c in choices if c.value == default), None)).ask())
    print(f"\n{message}")
    for i, (v, lbl) in enumerate(items, 1):
        mark = f"  ({_s('default')})" if v == default else ""
        print(f"  {i:2d}. {lbl}{mark}")
    while True:
        answer = input(f"  {_s('number')}: ").strip()
        if not answer and default is not None:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(items):
            return items[int(answer) - 1][0]


def text(message: str, default: str = "") -> str:
    if FANCY:
        return _done(questionary.text(message, default=default).ask()).strip()
    hint = f" [{default}]" if default else ""
    return (input(f"{message}{hint}: ").strip() or default)


def confirm(message: str, default: bool = True) -> bool:
    if FANCY:
        return _done(questionary.confirm(message, default=default).ask())
    yn = _s("yn")[0 if default else 1]
    answer = input(f"{message} ({yn}): ").strip().lower()
    return default if not answer else answer.startswith(("y", "כ"))
