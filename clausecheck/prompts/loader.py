import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Prompt:
    """A versioned prompt loaded from disk."""

    name: str
    version: str
    text: str


_HEADER_RE = re.compile(r"^# v(\S+)\s*$")


def load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt:
    """Load ``<name>.txt`` and split off its ``# v<N>`` header line."""
    base = Path(prompts_dir) if prompts_dir is not None else Path(__file__).resolve().parent
    path = base / f"{name}.txt"
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines:
        raise ValueError(f"prompt {name!r} is missing a version header")
    match = _HEADER_RE.match(lines[0].strip())
    if match is None:
        raise ValueError(f"prompt {name!r} is missing a version header")
    version = f"v{match.group(1)}"
    text = "\n".join(lines[1:])
    return Prompt(name=name, version=version, text=text)
