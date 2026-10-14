"""Validate retrieval judgments before running or scoring a search engine."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

Record = dict[str, Any]


def valid_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and value == path.as_posix()


def validate_span(span: object) -> None:
    if not isinstance(span, dict):
        raise ValueError("span must be an object")
    start, end = span.get("start_line"), span.get("end_line")
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        raise ValueError("invalid inclusive source span")


def validate_case(case: object) -> Record:
    if not isinstance(case, dict):
        raise ValueError("case must be an object")
    for key in ("id", "repo_id", "repo_commit", "query", "language", "purpose", "behavior_group"):
        if not isinstance(case.get(key), str) or not case[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if not re.fullmatch(r"[0-9a-f]{40,64}", case["repo_commit"]):
        raise ValueError("repo_commit must be an immutable git revision")
    if case["language"] not in ("en", "es"):
        raise ValueError("language must be en or es")
    if case["purpose"] not in ("implementation", "identity", "usage", "tests", "documentation"):
        raise ValueError("unknown judgment purpose")
    if type(case.get("answerable")) is not bool:
        raise ValueError("answerable must be boolean")
    alternatives = case.get("alternatives")
    if not isinstance(alternatives, list) or bool(alternatives) != case["answerable"]:
        raise ValueError("positive cases need alternatives; negative cases must have none")
    for alt in alternatives:
        if not isinstance(alt, dict) or not valid_path(alt.get("path")):
            raise ValueError("alternative path must be project relative")
        if not re.fullmatch(r"[0-9a-f]{64}", str(alt.get("source_hash", ""))):
            raise ValueError("source_hash must be SHA-256 of source bytes")
        anchors = alt.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise ValueError("alternative requires nonempty anchors")
        for anchor in anchors:
            validate_span(anchor)
        entity = alt.get("entity")
        if entity is not None:
            if not isinstance(entity, dict) or not all(
                isinstance(entity.get(k), str) and entity[k] for k in ("kind", "qualname")
            ):
                raise ValueError("entity needs kind and qualname")
            if entity.get("owner") is not None and not isinstance(entity["owner"], str):
                raise ValueError("entity owner must be a name or null")
            ordinal = entity.get("definition_ordinal")
            if type(ordinal) is not int or ordinal < 0:
                raise ValueError("entity requires nonnegative definition_ordinal")
    return case


@dataclass(frozen=True)
class RetrievalDataset:
    cases: tuple[Record, ...]
    sha256: str

    def __iter__(self) -> Iterator[Record]:
        return iter(self.cases)


def load_dataset(path: Path) -> RetrievalDataset:
    content = path.read_bytes()
    cases: list[Record] = []
    ids: set[str] = set()
    for n, line in enumerate(content.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = validate_case(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{path}:{n}: {exc}") from exc
        if case["id"] in ids:
            raise ValueError(f"duplicate case id: {case['id']}")
        ids.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("empty retrieval dataset")
    return RetrievalDataset(tuple(cases), hashlib.sha256(content).hexdigest())
