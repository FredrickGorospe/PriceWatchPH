from django.db import models
from django.db.models import Q

from catalogue.models import Sku
from ingestion.models import RawListing

CONDITION_CHOICES = [
    ("new", "New"),
    ("like_new", "Like new"),
    ("used", "Used"),
    ("for_parts", "For parts"),
]

RESOLUTION_METHOD_CHOICES = [
    ("exact_alias", "Exact alias"),
    ("fuzzy_match", "Fuzzy match"),
    ("human_confirmed", "Human confirmed"),
    ("unresolved", "Unresolved"),
]

PRICE_KIND_CHOICES = [
    ("asking", "Asking"),  # advertised price of a live listing
    ("realised", "Realised"),  # price a completed transaction actually cleared at
]

TRADE_SIDE_CHOICES = [
    ("buy", "Buy"),
    ("sell", "Sell"),
]


class Listing(models.Model):
    raw_listing = models.OneToOneField(RawListing, on_delete=models.PROTECT, related_name="listing")
    sku = models.ForeignKey(Sku, null=True, blank=True, on_delete=models.SET_NULL, related_name="listings")
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, null=True)
    location = models.TextField()
    resolution_confidence = models.DecimalField(max_digits=5, decimal_places=4)
    resolution_method = models.CharField(max_length=20, choices=RESOLUTION_METHOD_CHOICES)
    resolved_at = models.DateTimeField()
    reviewed_unresolved_at = models.DateTimeField(null=True, blank=True)
    # The timestamp PricePoint.day buckets on: COALESCE(raw_listing.occurred_at,
    # raw_listing.fetched_at), written by the resolver (phase 3) via
    # listings.observation.observed_at_for. Nullable only because TASK_004's
    # frozen tests construct Listings without it and CLAUDE.md forbids
    # editing a frozen test; NULL means "written before this field existed".
    # See TASK_005 Decisions 1 and 2.
    observed_at = models.DateTimeField(null=True, blank=True, default=None)
    # Asking (a live listing's advertised price) or realised (what a
    # completed transaction actually cleared at). Lives here rather than on
    # RawListing or Source because phase 5 reads Listing/Sku only, and the
    # property is row-level, not source-level — manual_capture can produce
    # both kinds. Nullable for the same frozen-test reason as observed_at.
    # See TASK_005 Decision 1 and docs/01_PLANNING.md §4.2.
    price_kind = models.CharField(max_length=20, choices=PRICE_KIND_CHOICES, null=True, blank=True, default=None)
    # Which side of a realised trade this was. NULL for an asking price
    # (nothing has traded) and legally NULL for a realised price too — a
    # "sold for X" capture is realised with an unknown side. See TASK_005
    # Decision 8.
    trade_side = models.CharField(max_length=10, choices=TRADE_SIDE_CHOICES, null=True, blank=True, default=None)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="listing_price_non_negative"),
            models.CheckConstraint(
                condition=Q(resolution_confidence__gte=0) & Q(resolution_confidence__lte=1),
                name="listing_resolution_confidence_in_unit_interval",
            ),
            models.CheckConstraint(
                condition=Q(condition__in=[c[0] for c in CONDITION_CHOICES]),
                name="listing_condition_in_vocabulary",
            ),
            models.CheckConstraint(
                condition=Q(resolution_method__in=[c[0] for c in RESOLUTION_METHOD_CHOICES]),
                name="listing_resolution_method_in_vocabulary",
            ),
            models.CheckConstraint(
                condition=Q(price_kind__in=[c[0] for c in PRICE_KIND_CHOICES]),
                name="listing_price_kind_in_vocabulary",
            ),
            models.CheckConstraint(
                condition=Q(trade_side__in=[c[0] for c in TRADE_SIDE_CHOICES]),
                name="listing_trade_side_in_vocabulary",
            ),
            models.CheckConstraint(
                # An asking price has no side — nothing has traded. The
                # converse is deliberately not enforced: a realised price may
                # legally omit trade_side. See TASK_005 Decision 8.
                condition=Q(trade_side__isnull=True) | Q(price_kind="realised"),
                name="listing_trade_side_requires_realised_price_kind",
            ),
        ]

    def __str__(self):
        return f"Listing #{self.pk} ({self.condition})"
