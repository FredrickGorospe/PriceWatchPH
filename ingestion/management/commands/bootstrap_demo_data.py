from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogue.models import Sku, SkuAlias
from ingestion import demo_data
from ingestion.models import RawListing
from listings.models import Listing
from listings.normalisation import normalise_title
from listings.resolver import resolve_raw_listing
from pricing.baselines import build_pricepoint
from pricing.models import DealFlag, PricePoint
from pricing.scoring import score_listing
from sources.models import Source


class Command(BaseCommand):
    help = (
        "Populate the deterministic pricewatchph_demo_v1 development/demo "
        "market-data corpus, gated by PRICEWATCHPH_ENABLE_DEMO_DATA."
    )

    def create_parser(self, prog_name, subcommand, **kwargs):
        # Without this, argparse's default prefix-abbreviation would let
        # "--force" silently match Django's built-in "--force-color" instead
        # of being rejected as unrecognized. See TASK_027 §4.
        return super().create_parser(
            prog_name, subcommand, allow_abbrev=False, **kwargs
        )

    def handle(self, *args, **options):
        if not settings.ENABLE_DEMO_DATA:
            raise CommandError(
                "Demo data bootstrap is disabled. "
                "Set PRICEWATCHPH_ENABLE_DEMO_DATA=1 to enable it."
            )

        with transaction.atomic():
            source = Source.objects.filter(name="manual_capture").first()
            if source is None:
                raise CommandError(
                    "Required approved Source manual_capture is missing."
                )

            skus_by_identity = self._ensure_skus()
            self._ensure_aliases(skus_by_identity)
            raw_by_external_id = self._ensure_raw_listings(source)
            listings_by_external_id = self._ensure_listings(
                skus_by_identity, raw_by_external_id
            )
            self._build_pricepoints(skus_by_identity)
            self._score_listings(listings_by_external_id)

            owned_ids = list(raw_by_external_id)
            owned_listings = Listing.objects.filter(
                raw_listing__external_id__in=owned_ids
            )
            pricepoints_count = sum(
                1
                for identity, condition, day in demo_data.PRICEPOINT_EXPECTATIONS
                if PricePoint.objects.filter(
                    sku=skus_by_identity[identity], condition=condition, day=day
                ).exists()
            )
            dealflags_count = DealFlag.objects.filter(
                listing__in=owned_listings
            ).count()
            unresolved_count = owned_listings.filter(
                sku__isnull=True, reviewed_unresolved_at__isnull=True
            ).count()

            self.stdout.write(
                f"Demo data ready: dataset={demo_data.DATASET} "
                f"skus={len(demo_data.SKUS)} "
                f"aliases={len(demo_data.ALIASES)} "
                f"raw_listings={len(owned_ids)} "
                f"listings={owned_listings.count()} "
                f"pricepoints={pricepoints_count} "
                f"dealflags={dealflags_count} "
                f"unresolved={unresolved_count}"
            )

    def _ensure_skus(self):
        skus_by_identity = {}
        for entry in demo_data.SKUS:
            brand, model, variant = entry["identity"]
            existing = Sku.objects.filter(
                brand=brand, model=model, variant=variant
            ).first()
            if existing is None:
                sku = Sku.objects.create(
                    brand=brand,
                    model=model,
                    variant=variant,
                    category=entry["category"],
                    launch_msrp=entry["launch_msrp"],
                    launch_date=entry["launch_date"],
                )
            else:
                if (
                    existing.category != entry["category"]
                    or existing.launch_msrp != entry["launch_msrp"]
                    or existing.launch_date != entry["launch_date"]
                ):
                    raise CommandError(
                        f"Conflicting demo Sku identity for {entry['identity']!r}: "
                        "existing row does not match the frozen manifest."
                    )
                sku = existing
            skus_by_identity[entry["identity"]] = sku
        return skus_by_identity

    def _ensure_aliases(self, skus_by_identity):
        for entry in demo_data.ALIASES:
            alias_text = entry["alias_text"]
            normalised_text = normalise_title(alias_text)
            sku = skus_by_identity[entry["identity"]]
            existing = SkuAlias.objects.filter(
                normalised_text=normalised_text
            ).first()
            if existing is None:
                SkuAlias.objects.create(
                    sku=sku,
                    alias_text=alias_text,
                    normalised_text=normalised_text,
                    source_of_truth="seed",
                )
            elif (
                existing.sku_id != sku.pk
                or existing.alias_text != alias_text
                or existing.source_of_truth != "seed"
            ):
                raise CommandError(
                    f"Conflicting demo SkuAlias identity for {alias_text!r}: "
                    "existing row does not match the frozen manifest."
                )

    def _ensure_raw_listings(self, source):
        raw_by_external_id = {}
        for row in demo_data.RAW_LISTINGS:
            # The bootstrap logical identity (source, external_id) is
            # deliberately narrower than the database's (source, external_id,
            # fetched_at) constraint — see TASK_027 §9 — so a mismatched
            # fetched_at must be treated as a conflict, not a second row.
            matches = list(
                RawListing.objects.filter(
                    source=source, external_id=row["external_id"]
                )
            )
            if len(matches) > 1:
                raise CommandError(
                    f"Conflicting demo RawListing identity for "
                    f"{row['external_id']!r}: multiple existing rows share "
                    "this logical identity."
                )
            if len(matches) == 1:
                existing = matches[0]
                if (
                    existing.raw_title != row["title"]
                    or existing.raw_price_text != row["price_text"]
                    or existing.raw_price != row["price"]
                    or existing.url != row["url"]
                    or existing.seller != ""
                    or existing.fetched_at != row["fetched_at"]
                    or existing.occurred_at != row["occurred_at"]
                    or existing.payload != row["payload"]
                ):
                    raise CommandError(
                        f"Conflicting demo RawListing identity for "
                        f"{row['external_id']!r}: existing row does not "
                        "match the frozen manifest."
                    )
                raw = existing
            else:
                raw = RawListing.objects.create(
                    source=source,
                    raw_title=row["title"],
                    raw_price_text=row["price_text"],
                    raw_price=row["price"],
                    url=row["url"],
                    seller="",
                    fetched_at=row["fetched_at"],
                    occurred_at=row["occurred_at"],
                    external_id=row["external_id"],
                    payload=row["payload"],
                )
            raw_by_external_id[row["external_id"]] = raw
        return raw_by_external_id

    def _ensure_listings(self, skus_by_identity, raw_by_external_id):
        listings_by_external_id = {}
        for row in demo_data.RAW_LISTINGS:
            raw = raw_by_external_id[row["external_id"]]
            existing_listing = Listing.objects.filter(raw_listing=raw).first()
            if existing_listing is not None:
                expected_sku = (
                    skus_by_identity[row["sku_identity"]]
                    if row["sku_identity"] is not None
                    else None
                )
                expected = {
                    "sku_id": expected_sku.pk if expected_sku else None,
                    "price": row["price"],
                    "condition": row["condition"],
                    "location": "",
                    "resolution_confidence": (
                        Decimal("1.0000") if expected_sku else Decimal("0.0000")
                    ),
                    "resolution_method": (
                        "exact_alias" if expected_sku else "unresolved"
                    ),
                    "observed_at": row["occurred_at"],
                    "price_kind": "asking",
                    "trade_side": None,
                }
                mismatched = any(
                    getattr(existing_listing, field) != value
                    for field, value in expected.items()
                )
                if mismatched:
                    raise CommandError(
                        f"Conflicting demo Listing identity for "
                        f"{row['external_id']!r}: existing Listing does not "
                        "match the expected resolution."
                    )
            # Safe to delegate now: either there was no prior Listing, or the
            # check above proved the prior one already matches, so the
            # resolver cannot silently "repair" real drift. See TASK_027 §10.
            listings_by_external_id[row["external_id"]] = resolve_raw_listing(raw)
        return listings_by_external_id

    def _build_pricepoints(self, skus_by_identity):
        for (identity, condition, day), expected in (
            demo_data.PRICEPOINT_EXPECTATIONS.items()
        ):
            sku = skus_by_identity[identity]
            existing = PricePoint.objects.filter(
                sku=sku, condition=condition, day=day
            ).first()
            if existing is not None and (
                existing.n_listings != expected["n_listings"]
                or existing.median != expected["median"]
                or existing.p25 != expected["p25"]
                or existing.p75 != expected["p75"]
                or existing.mad != expected["mad"]
            ):
                raise CommandError(
                    f"Conflicting demo PricePoint identity for {identity!r} "
                    f"{condition} {day}: existing sealed row does not match "
                    "the frozen manifest."
                )
            # build_pricepoint() is production-authoritative and silently
            # reuses any pre-existing row for this identity — the check
            # above is what stops a conflicting sealed PricePoint from being
            # accepted unnoticed. See TASK_027 §11 and §13.
            build_pricepoint(sku=sku, condition=condition, as_of_day=day)

    def _score_listings(self, listings_by_external_id):
        for row in demo_data.RAW_LISTINGS:
            listing = listings_by_external_id[row["external_id"]]
            score_listing(listing=listing)
