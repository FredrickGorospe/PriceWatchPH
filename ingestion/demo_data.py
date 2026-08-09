"""Frozen synthetic manifest for TASK_027's deterministic demo bootstrap.

Every value here is fixed by TASK_027 (sections 7-11) and the frozen test
tests/test_task_027_deterministic_demo_data_bootstrap.py. Nothing here is
computed from wall-clock time or improvised at runtime — this module is pure
data. ingestion.management.commands.bootstrap_demo_data owns the create-or-
reuse-or-conflict orchestration and delegates resolution and pricing to the
existing production services.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


DATASET = "pricewatchph_demo_v1"

D1 = date(2026, 6, 15)
D2 = date(2026, 7, 15)

ATLAS_IDENTITY = ("PriceWatchPH Demo", "Atlas GPU", "12GB")
BEACON_IDENTITY = ("PriceWatchPH Demo", "Beacon CPU", "8C16T")

ATLAS_CANONICAL_ALIAS = "PRICEWATCHPH DEMO // Atlas GPU 12GB"
ATLAS_ALTERNATE_ALIAS = "DEMO Atlas-GPU / 12 GB"
BEACON_CANONICAL_ALIAS = "PRICEWATCHPH DEMO // Beacon CPU 8C16T"
BEACON_ALTERNATE_ALIAS = "DEMO Beacon-CPU / 8C 16T"
UNRESOLVED_TITLE = "PRICEWATCHPH DEMO // Mystery Component Prototype"

# Fall inside both the D1 and D2 90-day Manila windows. See TASK_027 §7.
_HISTORY_DAYS = (
    date(2026, 4, 27),
    date(2026, 5, 7),
    date(2026, 5, 17),
    date(2026, 5, 27),
    date(2026, 6, 5),
)

SKUS = (
    {
        "identity": ATLAS_IDENTITY,
        "category": "gpu",
        "launch_msrp": Decimal("40000.00"),
        "launch_date": date(2025, 1, 15),
    },
    {
        "identity": BEACON_IDENTITY,
        "category": "cpu",
        "launch_msrp": Decimal("25000.00"),
        "launch_date": date(2025, 2, 15),
    },
)

ALIASES = (
    {"identity": ATLAS_IDENTITY, "alias_text": ATLAS_CANONICAL_ALIAS},
    {"identity": ATLAS_IDENTITY, "alias_text": ATLAS_ALTERNATE_ALIAS},
    {"identity": BEACON_IDENTITY, "alias_text": BEACON_CANONICAL_ALIAS},
    {"identity": BEACON_IDENTITY, "alias_text": BEACON_ALTERNATE_ALIAS},
)


def _instants(day: date) -> tuple[datetime, datetime]:
    # Noon Manila (UTC+8) is 04:00 UTC; fetched five minutes later. A fixed
    # clock, not wall-clock time, keeps a fresh database reproducible. See
    # TASK_027 §7.
    occurred_at = datetime(day.year, day.month, day.day, 4, 0, tzinfo=timezone.utc)
    return occurred_at, occurred_at + timedelta(minutes=5)


def _raw_listing(suffix, identity, condition, day, price_text, title):
    external_id = f"{DATASET}:{suffix}"
    slug = suffix.replace(":", "-")
    url = f"https://pricewatchph-demo.invalid/listings/{slug}/"
    occurred_at, fetched_at = _instants(day)
    payload = {
        "title": title,
        "price": price_text,
        "url": url,
        "external_id": external_id,
        "stated_condition": condition,
        "stated_price_kind": "asking",
    }
    return {
        "external_id": external_id,
        "sku_identity": identity,
        "condition": condition,
        "day": day,
        "price": Decimal(price_text),
        "price_text": price_text,
        "title": title,
        "url": url,
        "occurred_at": occurred_at,
        "fetched_at": fetched_at,
        "payload": payload,
    }


RAW_LISTINGS = (
    _raw_listing("atlas:used:history:01", ATLAS_IDENTITY, "used", _HISTORY_DAYS[0], "10000.00", ATLAS_CANONICAL_ALIAS),
    _raw_listing("atlas:used:history:02", ATLAS_IDENTITY, "used", _HISTORY_DAYS[1], "11000.00", ATLAS_ALTERNATE_ALIAS),
    _raw_listing("atlas:used:history:03", ATLAS_IDENTITY, "used", _HISTORY_DAYS[2], "12000.00", ATLAS_CANONICAL_ALIAS),
    _raw_listing("atlas:used:history:04", ATLAS_IDENTITY, "used", _HISTORY_DAYS[3], "13000.00", ATLAS_ALTERNATE_ALIAS),
    _raw_listing("atlas:used:history:05", ATLAS_IDENTITY, "used", _HISTORY_DAYS[4], "14000.00", ATLAS_CANONICAL_ALIAS),
    _raw_listing("atlas:used:ordinary:d1", ATLAS_IDENTITY, "used", D1, "12500.00", ATLAS_ALTERNATE_ALIAS),
    _raw_listing("atlas:used:deal:d2", ATLAS_IDENTITY, "used", D2, "9250.00", ATLAS_CANONICAL_ALIAS),
    _raw_listing("atlas:new:history:01", ATLAS_IDENTITY, "new", date(2026, 7, 5), "16000.00", ATLAS_ALTERNATE_ALIAS),
    _raw_listing("beacon:like_new:history:01", BEACON_IDENTITY, "like_new", _HISTORY_DAYS[0], "20000.00", BEACON_CANONICAL_ALIAS),
    _raw_listing("beacon:like_new:history:02", BEACON_IDENTITY, "like_new", _HISTORY_DAYS[1], "21000.00", BEACON_ALTERNATE_ALIAS),
    _raw_listing("beacon:like_new:history:03", BEACON_IDENTITY, "like_new", _HISTORY_DAYS[2], "22000.00", BEACON_CANONICAL_ALIAS),
    _raw_listing("beacon:like_new:history:04", BEACON_IDENTITY, "like_new", _HISTORY_DAYS[3], "23000.00", BEACON_ALTERNATE_ALIAS),
    _raw_listing("beacon:like_new:history:05", BEACON_IDENTITY, "like_new", _HISTORY_DAYS[4], "24000.00", BEACON_CANONICAL_ALIAS),
    _raw_listing("beacon:like_new:ordinary:d1", BEACON_IDENTITY, "like_new", D1, "22500.00", BEACON_ALTERNATE_ALIAS),
    _raw_listing("beacon:like_new:deal:d2", BEACON_IDENTITY, "like_new", D2, "19250.00", BEACON_CANONICAL_ALIAS),
    _raw_listing("unresolved:mystery:d2", None, "used", D2, "9999.00", UNRESOLVED_TITLE),
)

# The exact (sku, condition, as_of_day) identities build_pricepoint() is
# called for, in stable (day, sku natural key, condition) order, together
# with the exact statistics the production Type-7/raw-MAD implementation is
# expected to derive from the manifest's controlled evidence. Both scored
# SKUs have five pre-D1 history observations, so both get a D1 baseline; the
# D1 "ordinary" rows become each SKU's sixth D2 history point; the Atlas
# "new" row proves same-SKU condition separation. See TASK_027 §11.
PRICEPOINT_EXPECTATIONS = {
    (ATLAS_IDENTITY, "used", D1): {
        "n_listings": 5,
        "median": Decimal("12000.0000"),
        "p25": Decimal("11000.0000"),
        "p75": Decimal("13000.0000"),
        "mad": Decimal("1000.0000"),
    },
    (BEACON_IDENTITY, "like_new", D1): {
        "n_listings": 5,
        "median": Decimal("22000.0000"),
        "p25": Decimal("21000.0000"),
        "p75": Decimal("23000.0000"),
        "mad": Decimal("1000.0000"),
    },
    (ATLAS_IDENTITY, "new", D2): {
        "n_listings": 1,
        "median": Decimal("16000.0000"),
        "p25": Decimal("16000.0000"),
        "p75": Decimal("16000.0000"),
        "mad": Decimal("0.0000"),
    },
    (ATLAS_IDENTITY, "used", D2): {
        "n_listings": 6,
        "median": Decimal("12250.0000"),
        "p25": Decimal("11250.0000"),
        "p75": Decimal("12875.0000"),
        "mad": Decimal("1000.0000"),
    },
    (BEACON_IDENTITY, "like_new", D2): {
        "n_listings": 6,
        "median": Decimal("22250.0000"),
        "p25": Decimal("21250.0000"),
        "p75": Decimal("22875.0000"),
        "mad": Decimal("1000.0000"),
    },
}
