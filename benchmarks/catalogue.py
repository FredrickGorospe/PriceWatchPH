"""Load and install the frozen synthetic benchmark catalogue."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


SCHEMA_VERSION = "benchmark_catalogue.v1"
FIXTURE_VERSION = "1.0.0"
CATEGORY_COUNTS = {
    "gpu": 30,
    "cpu": 25,
    "ram": 20,
    "mobo": 20,
    "monitor": 15,
    "peripheral": 10,
}
ALIAS_POLICY = {
    "aliases_per_sku": 2,
    "source_of_truth": "seed",
    "generated_evaluation_titles_may_be_added": False,
}
_TOP_LEVEL_FIELDS = {
    "schema_version",
    "fixture_version",
    "catalogue_kind",
    "sku_count",
    "category_counts",
    "alias_policy",
    "skus",
}
_SKU_FIELDS = {
    "natural_key",
    "category",
    "brand",
    "model",
    "variant",
    "launch_msrp",
    "launch_date",
    "family_token",
    "ambiguity_group",
    "aliases",
}
_ALIAS_FIELDS = {"alias_text", "source_of_truth"}
_NATURAL_KEY_PATTERN = re.compile(
    r"bench_(gpu|cpu|ram|mobo|monitor|peripheral)_\d{3}"
)
_MONEY_PATTERN = re.compile(r"[0-9]+\.[0-9]{2}")


@dataclass(frozen=True)
class AliasValue:
    alias_text: str
    source_of_truth: str


@dataclass(frozen=True)
class SkuValue:
    natural_key: str
    category: str
    brand: str
    model: str
    variant: str
    launch_msrp: str
    launch_date: str
    family_token: str
    ambiguity_group: str
    aliases: tuple[AliasValue, ...]


@dataclass(frozen=True)
class CatalogueValue:
    skus: tuple[SkuValue, ...]
    sha256: str


def _require_exact_fields(value: dict, expected: set[str], context: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{context} must have the exact frozen fields")


def _parse_sku(value: dict) -> SkuValue:
    _require_exact_fields(value, _SKU_FIELDS, "SKU")
    natural_key = value["natural_key"]
    if not isinstance(natural_key, str) or not _NATURAL_KEY_PATTERN.fullmatch(natural_key):
        raise ValueError("SKU natural_key does not match the frozen format")
    if value["category"] not in CATEGORY_COUNTS:
        raise ValueError("SKU category is outside the frozen vocabulary")
    for field in ("brand", "model", "family_token", "ambiguity_group"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"SKU {field} must be a non-empty string")
    if not isinstance(value["variant"], str):
        raise ValueError("SKU variant must be a string")
    if not isinstance(value["launch_msrp"], str) or not _MONEY_PATTERN.fullmatch(
        value["launch_msrp"]
    ):
        raise ValueError("SKU launch_msrp must be fixed two-place Decimal text")
    try:
        if Decimal(value["launch_msrp"]) <= 0:
            raise ValueError("SKU launch_msrp must be positive")
    except InvalidOperation as error:
        raise ValueError("SKU launch_msrp must be Decimal text") from error
    try:
        date.fromisoformat(value["launch_date"])
    except (TypeError, ValueError) as error:
        raise ValueError("SKU launch_date must be an ISO date") from error

    aliases = value["aliases"]
    if not isinstance(aliases, list) or len(aliases) != 2:
        raise ValueError("Every benchmark SKU must have exactly two aliases")
    parsed_aliases = []
    for alias in aliases:
        _require_exact_fields(alias, _ALIAS_FIELDS, "alias")
        if not isinstance(alias["alias_text"], str) or not alias["alias_text"]:
            raise ValueError("Alias text must be non-empty")
        if alias["source_of_truth"] != "seed":
            raise ValueError("Benchmark aliases must be frozen seed evidence")
        parsed_aliases.append(AliasValue(**alias))

    canonical = " ".join(
        part for part in (value["brand"], value["model"], value["variant"]) if part
    )
    if parsed_aliases[0].alias_text != canonical:
        raise ValueError("The first alias must be the canonical SKU title")
    return SkuValue(
        natural_key=natural_key,
        category=value["category"],
        brand=value["brand"],
        model=value["model"],
        variant=value["variant"],
        launch_msrp=value["launch_msrp"],
        launch_date=value["launch_date"],
        family_token=value["family_token"],
        ambiguity_group=value["ambiguity_group"],
        aliases=tuple(parsed_aliases),
    )


def load_catalogue(path: str | Path) -> CatalogueValue:
    """Return an immutable, validated view of the exact fixture bytes."""
    fixture_path = Path(path)
    raw_bytes = fixture_path.read_bytes()
    if not raw_bytes.endswith(b"\n"):
        raise ValueError("Benchmark catalogue fixture must end with a newline")
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Benchmark catalogue fixture must be UTF-8 JSON") from error
    _require_exact_fields(document, _TOP_LEVEL_FIELDS, "catalogue")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported benchmark catalogue schema")
    if document["fixture_version"] != FIXTURE_VERSION:
        raise ValueError("Unsupported benchmark catalogue fixture version")
    if document["catalogue_kind"] != "synthetic_benchmark_only":
        raise ValueError("Catalogue is not marked synthetic benchmark only")
    if document["sku_count"] != 120:
        raise ValueError("Benchmark catalogue must contain exactly 120 SKUs")
    if document["category_counts"] != CATEGORY_COUNTS:
        raise ValueError("Benchmark category counts differ from the frozen contract")
    if document["alias_policy"] != ALIAS_POLICY:
        raise ValueError("Benchmark alias policy differs from the frozen contract")
    if not isinstance(document["skus"], list) or len(document["skus"]) != 120:
        raise ValueError("Benchmark catalogue must contain exactly 120 SKU objects")

    skus = tuple(_parse_sku(value) for value in document["skus"])
    if Counter(sku.category for sku in skus) != Counter(CATEGORY_COUNTS):
        raise ValueError("Benchmark SKU category composition is invalid")
    if len({sku.natural_key for sku in skus}) != 120:
        raise ValueError("Benchmark natural keys must be globally unique")
    if len({(sku.brand, sku.model, sku.variant) for sku in skus}) != 120:
        raise ValueError("Benchmark SKU identities must be globally unique")

    groups: dict[str, list[SkuValue]] = defaultdict(list)
    for sku in skus:
        groups[sku.ambiguity_group].append(sku)
    if len(groups) != 24:
        raise ValueError("Benchmark catalogue must have exactly 24 ambiguity groups")
    for members in groups.values():
        if len(members) != 5:
            raise ValueError("Each ambiguity group must have exactly five members")
        if len({member.category for member in members}) != 1:
            raise ValueError("An ambiguity group cannot span categories")
        if len({member.family_token for member in members}) != 1:
            raise ValueError("An ambiguity group must share one family token")

    # Import only when validation needs release semantics, keeping this module
    # usable for byte inspection without initialising Django.
    from listings.normalisation import normalise_title

    normalised_aliases = [
        normalise_title(alias.alias_text)
        for sku in skus
        for alias in sku.aliases
    ]
    if len(set(normalised_aliases)) != 240:
        raise ValueError("All benchmark aliases must be globally unique after normalisation")
    for sku in skus:
        if normalise_title(sku.aliases[0].alias_text) == normalise_title(
            sku.aliases[1].alias_text
        ):
            raise ValueError("A structural alternate must differ from its canonical alias")

    return CatalogueValue(
        skus=skus,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def install_catalogue(catalogue: CatalogueValue) -> None:
    """Install frozen SKUs and aliases without rewriting existing evidence."""
    from django.db import transaction

    from catalogue.models import Sku, SkuAlias
    from listings.normalisation import normalise_title

    with transaction.atomic():
        for value in catalogue.skus:
            sku, created = Sku.objects.get_or_create(
                brand=value.brand,
                model=value.model,
                variant=value.variant,
                defaults={
                    "category": value.category,
                    "launch_msrp": Decimal(value.launch_msrp),
                    "launch_date": date.fromisoformat(value.launch_date),
                },
            )
            if not created and (
                sku.category != value.category
                or sku.launch_msrp != Decimal(value.launch_msrp)
                or sku.launch_date != date.fromisoformat(value.launch_date)
            ):
                raise ValueError(
                    f"Incompatible pre-existing SKU identity: {value.natural_key}"
                )
            for alias in value.aliases:
                normalised_text = normalise_title(alias.alias_text)
                existing = SkuAlias.objects.filter(
                    normalised_text=normalised_text
                ).first()
                if existing is not None:
                    if (
                        existing.sku_id != sku.pk
                        or existing.alias_text != alias.alias_text
                        or existing.source_of_truth != alias.source_of_truth
                    ):
                        raise ValueError(
                            "Incompatible pre-existing benchmark alias: "
                            f"{alias.alias_text}"
                        )
                    continue
                SkuAlias.objects.create(
                    sku=sku,
                    alias_text=alias.alias_text,
                    normalised_text=normalised_text,
                    source_of_truth=alias.source_of_truth,
                )
