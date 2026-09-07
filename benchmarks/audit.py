"""Deterministic owner-review samples for generated benchmark titles."""

from __future__ import annotations

import hashlib
from itertools import islice

from benchmarks.catalogue import CatalogueValue
from benchmarks.generator import GENERATOR_VERSION, MASTER_SEED, Observation


def _audit_rank(
    *, selector: str, catalogue_sha256: str, difficulty: str, observation_key: str
) -> str:
    parts = (
        GENERATOR_VERSION,
        MASTER_SEED,
        catalogue_sha256,
        selector,
        difficulty,
        observation_key,
    )
    framed = b"".join(
        str(len(str(part).encode("utf-8"))).encode("ascii")
        + b":"
        + str(part).encode("utf-8")
        + b";"
        for part in parts
    )
    return hashlib.sha256(framed).hexdigest()


def select_semantic_audit(
    *, records, catalogue: CatalogueValue, selector: str
) -> dict[str, object]:
    """Select 25 pending human-review entries independently per class."""
    if not isinstance(selector, str) or not selector:
        raise ValueError("selector must be a non-empty string")
    materialised = list(islice(records, 1000))
    sku_by_key = {sku.natural_key: sku for sku in catalogue.skus}
    grouped: dict[str, list[tuple[str, Observation]]] = {
        difficulty: [] for difficulty in "ABCD"
    }
    for record in materialised:
        difficulty = record.label.difficulty
        if difficulty not in grouped:
            raise ValueError("record has an unsupported difficulty")
        grouped[difficulty].append(
            (
                _audit_rank(
                    selector=selector,
                    catalogue_sha256=catalogue.sha256,
                    difficulty=difficulty,
                    observation_key=record.label.observation_key,
                ),
                record,
            )
        )

    entries = []
    for difficulty in "ABCD":
        ranked = sorted(grouped[difficulty], key=lambda item: (item[0], item[1].label.observation_key))
        if len(ranked) < 25:
            raise ValueError("semantic audit requires at least 25 records per class")
        for _, record in ranked[:25]:
            candidates = [
                sku_by_key[key] for key in record.label.candidate_sku_keys
            ]
            catalogue_context = [
                {
                    "natural_key": sku.natural_key,
                    "category": sku.category,
                    "brand": sku.brand,
                    "model": sku.model,
                    "variant": sku.variant,
                    "family_token": sku.family_token,
                    "ambiguity_group": sku.ambiguity_group,
                }
                for sku in candidates
            ]
            entries.append(
                {
                    "generated_title": record.production.raw_title,
                    "difficulty": difficulty,
                    "expected_sku_key": record.label.expected_sku_key,
                    "candidate_sku_keys": list(record.label.candidate_sku_keys),
                    "transformations": list(record.label.transformations),
                    "catalogue_context": catalogue_context,
                }
            )
    return {
        "review_status": "pending_owner_review",
        "selector": selector,
        "entries": entries,
    }
