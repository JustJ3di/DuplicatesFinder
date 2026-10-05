from __future__ import annotations

from typing import Iterable, List, Tuple


def automatic_candidate_paths(groups: Iterable[Tuple[str, List[str]]]) -> List[str]:
    return [path for _, paths in groups for path in paths[1:]]