from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalogue.models import SkuAlias
from ingestion.models import RawListing
from listings.models import Listing
from listings.normalisation import normalise_title
from listings.observation import observed_at_for

# The only Source allowed to supply the narrow "this is an asking price"
# fact, and the only value recognized for it — every other source or value
# falls through to NULL. See TASK_027 §6.
_ASKING_PRICE_KIND = "asking"
_ASKING_TRUSTED_SOURCE = "manual_capture"


def _price_kind_and_trade_side(*, payload: dict, source_name: str) -> tuple:
    trade_side = payload.get("stated_trade_side")
    if trade_side is not None:
        return "realised", trade_side

    if (
        source_name == _ASKING_TRUSTED_SOURCE
        and payload.get("stated_price_kind") == _ASKING_PRICE_KIND
    ):
        return _ASKING_PRICE_KIND, None

    return None, None


def _automatic_values(raw_listing: RawListing) -> dict:
    normalised_title = normalise_title(raw_listing.raw_title)
    alias = SkuAlias.objects.filter(normalised_text=normalised_title).first()
    payload = raw_listing.payload if isinstance(raw_listing.payload, dict) else {}
    price_kind, trade_side = _price_kind_and_trade_side(
        payload=payload,
        source_name=raw_listing.source.name,
    )

    if alias is None:
        sku_id = None
        resolution_method = "unresolved"
        resolution_confidence = Decimal("0.0000")
    else:
        sku_id = alias.sku_id
        resolution_method = "exact_alias"
        resolution_confidence = Decimal("1.0000")

    return {
        "sku_id": sku_id,
        "price": raw_listing.raw_price,
        "condition": payload.get("stated_condition"),
        "location": "",
        "resolution_confidence": resolution_confidence,
        "resolution_method": resolution_method,
        "observed_at": observed_at_for(raw_listing),
        "price_kind": price_kind,
        "trade_side": trade_side,
    }


@transaction.atomic
def resolve_raw_listing(raw_listing: RawListing) -> Listing:
    """Create or refresh the single machine-derived Listing for an observation."""
    # Locking the immutable parent serializes concurrent first derivations.
    locked_raw_listing = RawListing.objects.select_for_update().get(pk=raw_listing.pk)
    listing = (
        Listing.objects.select_for_update()
        .filter(raw_listing_id=locked_raw_listing.pk)
        .first()
    )

    # Human decisions remain authoritative over every automatic field.
    if listing is not None and listing.resolution_method == "human_confirmed":
        return listing

    values = _automatic_values(locked_raw_listing)

    if listing is None:
        return Listing.objects.create(
            raw_listing=locked_raw_listing,
            resolved_at=timezone.now(),
            **values,
        )

    machine_result_changed = listing.resolution_method != values["resolution_method"]
    if values["resolution_method"] == "exact_alias":
        machine_result_changed = machine_result_changed or listing.sku_id != values["sku_id"]

    if machine_result_changed:
        # A completed review survives only while the machine result stays identical.
        values["reviewed_unresolved_at"] = None

    changed_fields = []
    for field_name, value in values.items():
        if getattr(listing, field_name) != value:
            setattr(listing, field_name, value)
            changed_fields.append(field_name)

    if not changed_fields:
        return listing

    listing.resolved_at = timezone.now()
    listing.save(update_fields=[*changed_fields, "resolved_at"])
    return listing
