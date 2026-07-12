"""Rule-based prompt rewriter that turns abstract or domain-specific phrases
into concrete, SAM3-friendly descriptions.

SAM3 was trained to match short, everyday descriptions that include shape,
color, and key parts ("a flatbed cart with handle and wheels").  Generic or
domain terms like "platform trolley" or "mining utility vehicle" frequently
yield 0 candidates, so the pipeline offers an offline rewriter that maps
common keywords to richer phrasings before SAM3 is invoked.

The rewriter is intentionally a pure function with no I/O and no LLM
dependency.  It is meant to be deterministic, fully unit-testable, and cheap
enough to run on every CLI invocation.  A future Claude-API-backed layer can
replace this without changing the function signature.
"""
from __future__ import annotations

from typing import Iterable


# Keyword → SAM3-friendly phrase.  Order matters: the first match wins, so
# put more specific keywords before broader ones.  Keep entries lowercase;
# matching is case-insensitive.
_PROMPT_HINTS: dict[str, str] = {
    # Vehicles and moving equipment
    "trolley": "a flatbed cart with handle and wheels",
    "cart": "a wheeled flatbed cart with handle",
    "dump truck": "a heavy mining dump truck with large wheels",
    "truck": "a heavy utility truck with cab and wheels",
    "loader": "a wheel loader with bucket and tires",
    "excavator": "an excavator with arm, bucket, and tracks",
    "drill rig": "a mining drill rig with mast and rotating bit",
    "drill": "a hand-held drill with rotating bit",
    "shovel": "an excavator shovel with metal blade",
    "bulldozer": "a bulldozer with blade and tracks",
    "hauler": "a mining haul truck with large bed",
    # Loose bulk material
    "ore pile": "a pile of rough mineral rocks",
    "ore": "a pile of rough mineral rocks",
    "rock pile": "a pile of rough mineral rocks",
    "gravel": "a pile of small grey gravel stones",
    "sand": "a pile of fine sand grains",
    "coal": "a pile of dark coal chunks",
    # Discrete solids
    "rock": "a single rough rock with visible facets",
    "boulder": "a large rough boulder",
    "stone": "a single grey stone",
    # Containers
    "bucket": "an open bucket with handle and cavity",
    "container": "an open container vessel with cavity",
    "barrel": "a cylindrical metal barrel",
    "hopper": "an open hopper with funnel shape",
    "vessel": "an open container vessel with cavity",
    # Common handheld tools and props (baseline prompts work well, but
    # include for completeness)
    "hammer": "a hammer with wooden handle and metal head",
    "wrench": "a metal wrench with adjustable jaw",
    "cable": "a coiled industrial cable",
    "pipe": "a cylindrical metal pipe",
    "beam": "a horizontal steel I-beam",
    # Cups and mugs (also covered by category inference, but kept here for
    # direct-prompt hits)
    "mug": "a red ceramic mug with handle",
    "cup": "an open ceramic cup",
    "teapot": "a ceramic teapot with spout and handle",
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def _match_keyword(text: str, keyword: str) -> bool:
    """Whole-word match against a normalized keyword phrase."""
    needle = keyword.lower()
    haystack = f" {text} "
    padded_needle = f" {needle} "
    return padded_needle in haystack


def rewrite_prompt(prompt: str, category: str = "") -> str:
    """Return a SAM3-friendly prompt.

    Looks for known keywords in either ``prompt`` or ``category`` (the
    first non-empty match wins).  Falls back to the original prompt when no
    hint matches.  The original prompt is returned unchanged when it already
    looks concrete (contains at least 5 words — a coarse signal).
    """
    candidates: list[str] = [_normalize(prompt), _normalize(category)]
    if not any(candidates):
        return prompt

    # Don't rewrite prompts that already look concrete.
    if len(prompt.split()) >= 5:
        return prompt

    haystacks: Iterable[str] = (h for h in candidates if h)
    for haystack in haystacks:
        for keyword, friendly in _PROMPT_HINTS.items():
            if _match_keyword(haystack, keyword):
                return friendly
    return prompt


def known_keywords() -> list[str]:
    """Return the sorted list of supported rewriter keywords (for CLI/docs)."""
    return sorted(_PROMPT_HINTS.keys())