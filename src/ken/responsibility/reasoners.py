"""Independent kinds of evidence, with an explicitly uncalibrated combination."""

from __future__ import annotations

import re
import unicodedata

from .model import Evidence, Inquiry, Symbol

_STOP = set(
    """who what which where how does do is are the a an of to for and in
    that this method function class code responsible handles responsible for
    quien quienes que cual cuales donde como el la los las un una de del para
    por y en se encarga metodo funcion clase codigo hace tal cosa hace""".split()
)


def terms(text: str) -> frozenset[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = "".join(
        c
        for c in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(c)
    )
    words = re.findall(r"[a-z0-9]+", text)
    # Only transparent inflection normalization; no hidden translation or
    # domain-specific synonym list that could silently change the question.
    return frozenset(
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        for w in words
        if w not in _STOP and len(w) > 1
    )


def overlap(query: frozenset[str], text: str) -> float:
    return len(query & terms(text)) / len(query) if query else 0.0


class DocumentationReasoner:
    def assess(self, inquiry: Inquiry, symbol: Symbol) -> tuple[Evidence, ...]:
        if not symbol.documentation:
            return ()
        lexical = overlap(inquiry.terms, symbol.documentation)
        score = max(0.0, min(1.0, inquiry.similarity))
        support = Evidence(
            "documentation",
            "supports",
            max(score, 0.85 * lexical),
            f"Documentation similarity {score:.3f}; term coverage {lexical:.3f} (correlated signals, combined by max).",
            "The documentation accurately describes this symbol's current behavior.",
        )
        out = [support]
        # These are conservative surface guards, not a general natural-language
        # proof system. Preserve the quote for cases they cannot interpret.
        for clause in re.split(r"[.;\n]|\bbut\b|\bsino\b", symbol.documentation):
            negative = re.search(
                r"\b(?:does not|do not|never|cannot|must not|no|nunca)\b(.*)",
                clause,
                re.I,
            )
            if negative and overlap(inquiry.terms, negative[1]) >= 0.5:
                out.append(
                    Evidence(
                        "documentation_guard",
                        "against",
                        0.9,
                        "Possible explicit denial: " + clause.strip()[:240],
                    )
                )
            if (
                re.search(
                    r"\b(?:may|might|could|would|if|podría|puede|si)\b", clause, re.I
                )
                and overlap(inquiry.terms, clause) >= 0.5
            ):
                out.append(
                    Evidence(
                        "documentation_guard",
                        "context",
                        0.5,
                        "Conditional documentation: " + clause.strip()[:240],
                        "The documented condition must hold; it has not been established.",
                    )
                )
            if (
                re.search(r"\b(?:delegat\w*|forward\w*|delega\w*)\b", clause, re.I)
                and overlap(inquiry.terms, clause) >= 0.5
            ):
                out.append(
                    Evidence(
                        "delegation",
                        "context",
                        0.5,
                        "Documentation describes delegation: " + clause.strip()[:240],
                        "Coordinating or delegating an operation does not establish who implements it.",
                    )
                )
        return tuple(out)


class NameReasoner:
    def assess(self, inquiry: Inquiry, symbol: Symbol) -> tuple[Evidence, ...]:
        strength = overlap(inquiry.terms, symbol.qualname)
        if not strength:
            return ()
        return (
            Evidence(
                "name",
                "supports",
                strength,
                "The symbol name shares responsibility terms.",
                "The name reflects behavior; a name alone does not prove it.",
            ),
        )


class CallsReasoner:
    def assess(self, inquiry: Inquiry, symbol: Symbol) -> tuple[Evidence, ...]:
        calls = [
            (name, line)
            for name, line in symbol.calls
            if overlap(inquiry.terms, name) >= 0.5
        ]
        if not calls:
            return ()
        sites = ", ".join(f"{name}:{line}" for name, line in calls[:4])
        return (
            Evidence(
                "calls",
                "context",
                0.4,
                "Contains call expressions related by name: " + sites,
                "Call targets and runtime execution are unresolved; this may be an orchestrator.",
            ),
        )


def confidence(evidence: tuple[Evidence, ...]) -> dict:
    """A ranking heuristic, not independent likelihoods or a proof probability.

    Repeating a contribution cannot inflate it. Calls are explanatory context,
    never a second vote that the caller implements its callee's behavior.
    """
    groups = {
        name: max(
            (
                e.strength
                for e in evidence
                if e.reasoner == name and e.direction == "supports"
            ),
            default=0.0,
        )
        for name in ("documentation", "name")
    }
    # New providers can contribute without modifying the orchestrator. Until
    # validated for this task, their positive support has conservative weight.
    additional = max(
        (
            e.strength
            for e in evidence
            if e.direction == "supports" and e.reasoner not in groups
        ),
        default=0.0,
    )
    score = max(groups["documentation"], 0.65 * groups["name"], 0.5 * additional)
    score += 0.05 * min(groups.values())
    if any(e.direction == "against" for e in evidence):
        score = min(score, 0.2)
    elif any(e.reasoner in {"documentation_guard", "delegation"} for e in evidence):
        score = min(score, 0.55)
    score = round(min(score, 0.95), 3)
    return {
        "score": score,
        "band": "strong" if score >= 0.7 else "moderate" if score >= 0.5 else "weak",
        "calibrated": False,
        "probability": None,
        "policy": "responsibility-evidence/1",
    }
