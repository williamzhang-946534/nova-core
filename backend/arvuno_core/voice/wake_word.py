import re
from dataclasses import dataclass


@dataclass(frozen=True)
class WakeWordMatch:
    detected: bool
    matched_term: str | None = None


class VoiceWakeWordModule:
    """Independent transcript gate; it never records or interprets audio."""

    def __init__(self, terms: tuple[str, ...] = ("arvuno", "阿夫努诺")) -> None:
        normalized = tuple(term.strip().lower() for term in terms if term.strip())
        if not normalized:
            raise ValueError("At least one wake word is required.")
        self._terms = normalized

    def match(self, transcript: str) -> WakeWordMatch:
        normalized = re.sub(r"\s+", " ", transcript).strip().lower()
        for term in self._terms:
            if re.search(rf"(?:^|\s){re.escape(term)}(?:\s|$)", normalized):
                return WakeWordMatch(True, term)
        return WakeWordMatch(False)


__all__ = ["VoiceWakeWordModule", "WakeWordMatch"]
