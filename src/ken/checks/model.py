"""A rule states an expectation; examples establish its intended discrimination."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from typing import Any


def digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("scope must be a project-relative POSIX path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or ".ken" in path.parts
        or ".git" in path.parts
    ):
        raise ValueError("scope must stay inside project source")
    return path.as_posix()


@dataclass(frozen=True)
class Rule:
    id: str
    query: str
    description: str
    path: str = "."
    expectation: str = "no_matches"
    examples: list[dict[str, Any]] = field(default_factory=list)
    libraries: dict[str, str] = field(default_factory=dict)

    @classmethod
    def read(cls, data: dict[str, Any]) -> Rule:
        try:
            rule = cls(**data)
        except (TypeError, AttributeError) as exc:
            raise ValueError("invalid rule fields") from exc
        if not isinstance(rule.id, str) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", rule.id
        ):
            raise ValueError("invalid rule id")
        if (
            not isinstance(rule.query, str)
            or not rule.query.lstrip().startswith('language "kql/2";')
            or len(rule.query) > 100_000
        ):
            raise ValueError(
                "a versioned KQL2 query of at most 100000 characters is required"
            )
        if (
            not isinstance(rule.description, str)
            or not rule.description.strip()
            or len(rule.description) > 2000
        ):
            raise ValueError("description must contain 1..2000 characters")
        if relative(rule.path) != rule.path:
            raise ValueError("use a normalized scope path")
        if rule.expectation not in {"no_matches", "some_match"}:
            raise ValueError("expectation must be no_matches or some_match")
        if (
            not isinstance(rule.libraries, dict)
            or len(rule.libraries) > 16
            or any(
                not isinstance(k, str) or not isinstance(v, str) or len(v) > 100_000
                for k, v in rule.libraries.items()
            )
        ):
            raise ValueError("libraries must map module names to bounded KQL source")
        if not isinstance(rule.examples, list) or len(rule.examples) > 12:
            raise ValueError("at most 12 examples are accepted")
        for example in rule.examples:
            if not isinstance(example, dict) or set(example) != {
                "name",
                "files",
                "expect",
            }:
                raise ValueError("examples require name, files and expect")
            if (
                not isinstance(example["name"], str)
                or not 1 <= len(example["name"]) <= 100
            ):
                raise ValueError("example name must contain 1..100 characters")
            if example["expect"] not in {"pass", "fail", "unknown"}:
                raise ValueError("example expect must be pass, fail or unknown")
            files = example["files"]
            if not isinstance(files, dict) or not 1 <= len(files) <= 20:
                raise ValueError("examples require 1..20 source files")
            for path, source in files.items():
                if (
                    relative(path) == "."
                    or not isinstance(source, str)
                    or len(source) > 100_000
                ):
                    raise ValueError("invalid example source")
        if len(json.dumps(asdict(rule))) > 1_000_000:
            raise ValueError("rule and examples exceed 1 MB")
        return rule

    @property
    def revision(self) -> str:
        return digest(asdict(self))


def judgment(result: dict[str, Any], expectation: str) -> str:
    """Certify only complete, covered, determinate observations in this scope."""
    if (
        not result.get("complete")
        or not result.get("coverage_complete")
        or result.get("results_truncated")
        or result.get("unknown_candidates")
        or result.get("reason")
    ):
        return "unknown"
    matched = bool(result.get("rows"))
    return "pass" if matched == (expectation == "some_match") else "fail"
