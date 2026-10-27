import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class ConfirmationSubject:
    tool_name: str
    input_fingerprint: str
    task_id: str | None

    def fingerprint(self) -> str:
        return hashlib.sha256(
            "|".join(
                [
                    self.tool_name,
                    self.input_fingerprint,
                    self.task_id or "",
                ]
            ).encode("utf-8")
        ).hexdigest()


class ConfirmationService:
    """Issues short-lived, single-use confirmation challenges in the local process."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        token_generator: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._token_generator = token_generator
        self._challenges: dict[str, tuple[datetime, str]] = {}
        self._lock = threading.Lock()

    def issue(self, subject: ConfirmationSubject) -> str:
        token = self._token_generator()
        digest = self._digest(token)
        with self._lock:
            self._cleanup_locked()
            self._challenges[digest] = (self._clock() + self._ttl, subject.fingerprint())
        return token

    def consume(self, token: str, subject: ConfirmationSubject) -> bool:
        digest = self._digest(token)
        with self._lock:
            self._cleanup_locked()
            challenge = self._challenges.get(digest)
            if challenge is None:
                return False
            expires_at, expected_subject = challenge
            del self._challenges[digest]
            now = self._clock()
            return now < expires_at and secrets.compare_digest(
                expected_subject, subject.fingerprint()
            )

    def _cleanup_locked(self) -> None:
        now = self._clock()
        expired = [key for key, (expires_at, _) in self._challenges.items() if expires_at <= now]
        for key in expired:
            del self._challenges[key]

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
