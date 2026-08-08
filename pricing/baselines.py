from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from catalogue.models import Sku
from listings.models import Listing
from pricing.models import PricePoint


CALCULATION_CONTRACT_VERSION = "asking_price_baseline_v1"

_CALCULATION_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
_FOUR_PLACES = Decimal("0.0001")
_MEDIAN_PERCENTILE = Decimal("0.50")
_LOWER_QUARTILE_PERCENTILE = Decimal("0.25")
_UPPER_QUARTILE_PERCENTILE = Decimal("0.75")


def _window_bounds(as_of_day: date) -> tuple[date, datetime, datetime]:
    window_start_day = as_of_day - timedelta(days=90)
    aggregation_timezone = ZoneInfo(settings.AGGREGATION_TIME_ZONE)
    # Calendar boundaries must be constructed in Manila before Django converts them to UTC.
    window_start = datetime.combine(
        window_start_day,
        time.min,
        tzinfo=aggregation_timezone,
    )
    window_end = datetime.combine(
        as_of_day,
        time.min,
        tzinfo=aggregation_timezone,
    )
    return window_start_day, window_start, window_end


def _eligible_prices(
    *,
    sku: Sku,
    condition: str,
    window_start: datetime,
    window_end: datetime,
) -> list[Decimal]:
    return list(
        Listing.objects.filter(
            sku=sku,
            condition=condition,
            condition__isnull=False,
            price__isnull=False,
            observed_at__isnull=False,
            observed_at__gte=window_start,
            observed_at__lt=window_end,
            price_kind="asking",
            resolution_method__in=("exact_alias", "human_confirmed"),
            resolution_confidence=Decimal("1.0000"),
        )
        .order_by("price")
        .values_list("price", flat=True)
    )


def _type_7_quantile(
    sorted_values: list[Decimal],
    percentile: Decimal,
) -> Decimal:
    position = Decimal(len(sorted_values) - 1) * percentile
    lower_index = int(position)
    upper_index = lower_index if position == lower_index else lower_index + 1
    fraction = position - Decimal(lower_index)
    return sorted_values[lower_index] + fraction * (
        sorted_values[upper_index] - sorted_values[lower_index]
    )


def _calculate_aggregates(
    prices: list[Decimal],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    with localcontext(_CALCULATION_CONTEXT):
        exact_median = _type_7_quantile(prices, _MEDIAN_PERCENTILE)
        p25 = _type_7_quantile(prices, _LOWER_QUARTILE_PERCENTILE)
        p75 = _type_7_quantile(prices, _UPPER_QUARTILE_PERCENTILE)
        deviations = sorted(abs(price - exact_median) for price in prices)
        mad = _type_7_quantile(deviations, _MEDIAN_PERCENTILE)

        return tuple(
            value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_EVEN)
            for value in (exact_median, p25, p75, mad)
        )


def build_pricepoint(
    *,
    sku: Sku,
    condition: str,
    as_of_day: date,
) -> PricePoint | None:
    identity = {
        "sku": sku,
        "condition": condition,
        "day": as_of_day,
    }

    try:
        return PricePoint.objects.get(**identity)
    except PricePoint.DoesNotExist:
        pass

    window_start_day, window_start, window_end = _window_bounds(as_of_day)
    prices = _eligible_prices(
        sku=sku,
        condition=condition,
        window_start=window_start,
        window_end=window_end,
    )
    if not prices:
        return None

    median, p25, p75, mad = _calculate_aggregates(prices)
    defaults = {
        "median": median,
        "p25": p25,
        "p75": p75,
        "n_listings": len(prices),
        "mad": mad,
        "window_start_day": window_start_day,
        "window_end_day": as_of_day,
        "calculated_at": timezone.now(),
        "calculation_contract_version": CALCULATION_CONTRACT_VERSION,
    }
    # The unique identity lets a concurrent winner remain sealed and authoritative.
    pricepoint, _created = PricePoint.objects.get_or_create(
        **identity,
        defaults=defaults,
    )
    return pricepoint
