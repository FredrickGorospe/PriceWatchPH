from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from django.utils import timezone

from listings.models import Listing
from pricing.bucketing import manila_day
from pricing.models import DealFlag, PricePoint


CALCULATION_CONTRACT_VERSION = "asking_price_baseline_v1"
SCORING_REASON = "asking_price_mad_v1"

_SCORING_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_FOUR_PLACES = Decimal("0.0001")
_DEAL_THRESHOLD = Decimal("-3.0000")
_MINIMUM_SAMPLE_SIZE = 5
_TRUSTED_RESOLUTION_METHODS = ("exact_alias", "human_confirmed")


def _is_eligible(listing: Listing) -> bool:
    return (
        listing.sku_id is not None
        and listing.price is not None
        and listing.condition is not None
        and listing.observed_at is not None
        and listing.price_kind == "asking"
        and listing.resolution_method in _TRUSTED_RESOLUTION_METHODS
        and listing.resolution_confidence == Decimal("1.0000")
    )


def _is_usable(pricepoint: PricePoint) -> bool:
    return (
        pricepoint.n_listings >= _MINIMUM_SAMPLE_SIZE
        and pricepoint.mad is not None
        and pricepoint.mad > Decimal("0.0000")
        and pricepoint.window_start_day is not None
        and pricepoint.window_end_day is not None
        and pricepoint.calculated_at is not None
        and pricepoint.calculation_contract_version
        == CALCULATION_CONTRACT_VERSION
    )


def _calculate_score(*, listing: Listing, pricepoint: PricePoint) -> Decimal:
    # A local context keeps scoring reproducible when callers alter Decimal globals.
    with localcontext(_SCORING_CONTEXT):
        raw_score = (listing.price - pricepoint.median) / pricepoint.mad
        return raw_score.quantize(_FOUR_PLACES)


def score_listing(*, listing: Listing) -> DealFlag | None:
    try:
        return DealFlag.objects.get(listing_id=listing.pk)
    except DealFlag.DoesNotExist:
        pass

    if not _is_eligible(listing):
        return None

    try:
        pricepoint = PricePoint.objects.get(
            sku_id=listing.sku_id,
            condition=listing.condition,
            day=manila_day(listing.observed_at),
        )
    except PricePoint.DoesNotExist:
        return None

    if not _is_usable(pricepoint):
        return None

    final_score = _calculate_score(listing=listing, pricepoint=pricepoint)
    if final_score > _DEAL_THRESHOLD:
        return None

    # The listing uniqueness constraint makes a concurrent winner authoritative.
    deal_flag, _created = DealFlag.objects.get_or_create(
        listing=listing,
        defaults={
            "score": final_score,
            "baseline_pricepoint": pricepoint,
            "reason": SCORING_REASON,
            "flagged_at": timezone.now(),
        },
    )
    return deal_flag
