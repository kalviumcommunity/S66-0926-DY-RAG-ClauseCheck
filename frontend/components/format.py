"""One place for how numbers, times and dates are written on screen.

Never a raw float, a millisecond count, a null or a dash: seconds with one decimal, whole
percentages, YYYY-MM-DD dates, and words ("Not measured") where there is no value.
"""

import datetime as dt

NOT_MEASURED = "Not measured"


def seconds(ms) -> str:
    """`3124.7` becomes `3.1 s`."""
    return NOT_MEASURED if ms is None else f"{ms / 1000:.1f} s"


def percent(value) -> str:
    """`0.683` becomes `68%`."""
    return NOT_MEASURED if value is None else f"{round(value * 100)}%"


def possessive(name: str) -> str:
    """`Orion’s`, `Helixa Cloud Systems’`."""
    return f"{name}’" if name.endswith("s") else f"{name}’s"


def plural(n: int, word: str, many: str | None = None) -> str:
    """`1 clause`, `2 clauses`."""
    return f"{n} {word if n == 1 else (many or word + 's')}"


def _local(iso: str | None) -> dt.datetime | None:
    if not iso:
        return None
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def clock(iso: str | None) -> str:
    """`2026-10-27T18:39:02Z` as local `18:39:02`."""
    moment = _local(iso)
    return moment.strftime("%H:%M:%S") if moment else ""


def short_clock(iso: str | None) -> str:
    moment = _local(iso)
    return moment.strftime("%H:%M") if moment else ""


def when(iso: str | None, now: dt.datetime | None = None) -> str:
    """`Today, 10:42`, `Yesterday`, `24 Oct`, or `Never`."""
    moment = _local(iso)
    if moment is None:
        return "Never"
    today = (now or dt.datetime.now().astimezone()).date()
    if moment.date() == today:
        return f"Today, {moment:%H:%M}"
    if moment.date() == today - dt.timedelta(days=1):
        return "Yesterday"
    return f"{moment.day} {moment:%b}"


def long_when(iso: str | None) -> str:
    """`27 Oct 2026, 18:40`."""
    moment = _local(iso)
    return f"{moment.day} {moment:%b %Y, %H:%M}" if moment else NOT_MEASURED


def day(iso: str | None) -> str:
    return (iso or "")[:10] or "Not dated"


def kinds(counts: dict) -> str:
    """`{"contract": 1, "amendment": 2}` as `Contract, 2 amendments`."""
    names = {
        "contract": ("Contract", "contracts"),
        "amendment": ("Amendment", "amendments"),
        "price_schedule": ("Price schedule", "price schedules"),
        "certificate": ("Certificate", "certificates"),
    }
    order = ["contract", "amendment", "price_schedule", "certificate"]
    parts = []
    for key in sorted(counts, key=lambda k: order.index(k) if k in order else 99):
        one, many = names.get(key, (key.replace("_", " ").capitalize(),) * 2)
        n = counts[key]
        parts.append(one if n == 1 else f"{n} {many}")
    return ", ".join(parts)
