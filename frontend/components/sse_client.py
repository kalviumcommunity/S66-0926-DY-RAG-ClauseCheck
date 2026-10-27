import json
from collections.abc import Iterable, Iterator

import httpx

BACKEND_DOWN = (
    'ClauseCheck couldn\'t generate an answer right now. This is a system error, not a "not found".'
)


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    event = None
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if event is not None or data_lines:
                data = {}
                if data_lines:
                    try:
                        data = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        data = {}
                yield (event or "message", data)
            event = None
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    # trailing event without blank line
    if event is not None or data_lines:
        data = {}
        if data_lines:
            try:
                data = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                data = {}
        yield (event or "message", data)


def stream_chat(
    base_url: str, payload: dict, client: httpx.Client | None = None, timeout: float = 60.0
) -> Iterator[tuple[str, dict]]:
    c = client or httpx.Client(base_url=base_url, timeout=timeout)
    try:
        with c.stream(
            "POST", f"{base_url.rstrip('/')}/chat/stream", json=payload, timeout=timeout
        ) as response:
            event = None
            data_lines: list[str] = []
            for line in response.iter_lines():
                if line == "":
                    if event is not None or data_lines:
                        data = {}
                        if data_lines:
                            try:
                                data = json.loads("\n".join(data_lines))
                            except json.JSONDecodeError:
                                data = {}
                        yield (event or "message", data)
                    event = None
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[len("data:") :].strip())
            if event is not None or data_lines:
                data = {}
                if data_lines:
                    try:
                        data = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        data = {}
                yield (event or "message", data)
    except Exception:
        yield ("error", {"message": BACKEND_DOWN})
        yield ("done", {"outcome": "error"})
