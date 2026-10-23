"""Training-prefix-only file target and filename vocabulary."""

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FileVocabulary:
    folders: tuple[str, ...] = ()
    tokens: tuple[str, ...] = ()

    @classmethod
    def fit(
        cls, rows: list[dict[str, Any]], labels: list[str], top_k: int = 15
    ) -> "FileVocabulary":
        counts = Counter(
            a for a in labels if a.startswith("MOVE_TO_FOLDER:") and a.partition(":")[2]
        )
        folders = tuple(a for a in sorted(counts, key=lambda a: (-counts[a], a)) if counts[a] >= 5)[
            :top_k
        ]
        tokens: Counter[str] = Counter()
        for row in rows:
            value = row.get("name_tokens", ())
            if not isinstance(value, (list, tuple, set)) or any(
                not isinstance(t, str) for t in value
            ):
                raise ValueError("invalid_filename_tokens")
            tokens.update({token.lower() for token in value if token})
        return cls(folders, tuple(sorted(tokens, key=lambda t: (-tokens[t], t))[:50]))

    def label(self, action: str) -> str:
        if action == "LEAVE":
            return action
        if action.startswith("MOVE_TO_FOLDER:") and action.partition(":")[2]:
            return action if action in self.folders else "OTHER"
        raise ValueError("unsupported_file_training_action")

    def row(self, row: dict[str, Any]) -> dict[str, Any]:
        # Old fixed tok_* fields must not leak a full-history vocabulary into a fold.
        result = {k: v for k, v in row.items() if k != "name_tokens" and not k.startswith("tok_")}
        value = row.get("name_tokens", ())
        if not isinstance(value, (list, tuple, set)) or any(not isinstance(t, str) for t in value):
            raise ValueError("invalid_filename_tokens")
        present = {t.lower() for t in value}
        result.update({f"tok_{t}": t in present for t in self.tokens})
        return result
