from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction


@pytest.fixture
def sku(db):
    from catalogue.models import Sku

    return Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )


def _pricepoint(sku, day):
    from pricing.models import PricePoint

    return PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=day,
        median=Decimal("15000.00"),
        p25=Decimal("14000.00"),
        p75=Decimal("16000.00"),
        n_listings=3,
    )


def test_manila_day_uses_the_manila_date_not_the_utc_date():
    """An instant late in the UTC day is already the next day in Manila, and buckets to the Manila date."""
    from pricing.bucketing import manila_day

    instant = datetime(2019, 3, 4, 16, 30, tzinfo=dt_timezone.utc)
    assert instant.date() == date(2019, 3, 4)
    assert manila_day(instant) == date(2019, 3, 5)


def test_manila_day_round_trips_a_manila_midnight_value():
    """A date-only source value stored as Manila midnight buckets back to exactly the date the source stated."""
    from ingestion.timeparse import manila_midnight
    from pricing.bucketing import manila_day

    assert manila_day(manila_midnight(date(2019, 3, 4))) == date(2019, 3, 4)


def test_both_sides_of_a_transaction_bucket_to_distinct_manila_days(sku):
    """A buy in March and a sell in November are two market events, and their PricePoints coexist."""
    from ingestion.timeparse import manila_midnight
    from pricing.bucketing import manila_day
    from pricing.models import PricePoint

    bought = manila_midnight(date(2019, 3, 4))
    sold = manila_midnight(date(2019, 11, 20))

    assert manila_day(bought) != manila_day(sold)
    _pricepoint(sku, manila_day(bought))
    _pricepoint(sku, manila_day(sold))
    assert PricePoint.objects.filter(sku=sku, condition="used").count() == 2


def test_import_time_stamping_would_collapse_both_sides_into_one_bucket(sku):
    """The regression this design prevents: if both rows carried import time, they share a Manila day and the second PricePoint is rejected."""
    from pricing.bucketing import manila_day

    import_instant = datetime(2026, 8, 1, 2, 30, tzinfo=dt_timezone.utc)
    day = manila_day(import_instant)

    _pricepoint(sku, day)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _pricepoint(sku, day)
