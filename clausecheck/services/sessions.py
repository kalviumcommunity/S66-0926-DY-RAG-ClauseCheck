import threading
import uuid
from dataclasses import dataclass, field


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class Session:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    supplier_id: str | None = None


class SessionStore:
    def __init__(self, history_turns: int = 3) -> None:
        self.history_turns = history_turns
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def new(self) -> str:
        sid = uuid.uuid4().hex
        with self._lock:
            self._sessions[sid] = Session(session_id=sid)
        return sid

    def get_or_create(self, session_id: str | None) -> Session:
        with self._lock:
            if session_id is None:
                sid = uuid.uuid4().hex
                self._sessions[sid] = Session(session_id=sid)
                return self._sessions[sid]
            if session_id not in self._sessions:
                self._sessions[session_id] = Session(session_id=session_id)
            return self._sessions[session_id]

    def scope_of(self, session_id: str | None) -> str | None:
        """The supplier a conversation is about (set by its first answer), or None.

        Does not create the session.
        """
        if session_id is None:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            return session.supplier_id if session else None

    def append(self, session_id: str, question: str, answer: str, supplier_id: str | None) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = Session(session_id=session_id)
                self._sessions[session_id] = session
            session.turns.append(Turn(question=question, answer=answer))
            session.turns = session.turns[-self.history_turns :]
            if supplier_id is not None:
                session.supplier_id = supplier_id
