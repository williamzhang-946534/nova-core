from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetentionPolicy:
    name: str
    label: str
    enabled: bool
    interval_seconds: int
    batch_size: int
    rules: dict[str, Any]

    def view(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "batch_size": self.batch_size,
            "rules": self.rules,
        }
