from django.db import models
from django.db.models import F, Q

from catalogue.models import Sku
from listings.models import CONDITION_CHOICES, Listing


class PricePoint(models.Model):
    sku = models.ForeignKey(Sku, on_delete=models.PROTECT, related_name="price_points")
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES)
    # The Manila calendar date of Listing.observed_at (see
    # pricing.bucketing.manila_day) — not of RawListing.fetched_at, which the
    # pricing engine is not responsible for reading (docs/00_PLANNING.md §1),
    # and not the UTC date, since a UTC day splits a Manila evening across
    # two buckets. Enforced by aggregation code (phase 5), not by this
    # column, which is a plain date. See TASK_005 Decisions 2 and 3.
    day = models.DateField()
    median = models.DecimalField(max_digits=12, decimal_places=2)
    p25 = models.DecimalField(max_digits=12, decimal_places=2)
    p75 = models.DecimalField(max_digits=12, decimal_places=2)
    n_listings = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sku", "condition", "day"], name="pricepoint_sku_condition_day_unique"),
            models.CheckConstraint(
                condition=Q(p25__lte=F("median")) & Q(median__lte=F("p75")),
                name="pricepoint_p25_median_p75_ordered",
            ),
            models.CheckConstraint(condition=Q(n_listings__gte=0), name="pricepoint_n_listings_non_negative"),
        ]

    def __str__(self):
        return f"{self.sku} {self.condition} {self.day}"


class DealFlag(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="deal_flags")
    # Signed, unbounded, in units of the baseline's MAD (median absolute
    # deviation): negative = priced below baseline (a deal), magnitude =
    # distance from baseline in MAD units. See Decision 4 in this task file —
    # the user's explicit choice, not a placeholder.
    score = models.DecimalField(max_digits=10, decimal_places=4)
    baseline_pricepoint = models.ForeignKey(PricePoint, on_delete=models.PROTECT, related_name="deal_flags")
    # No fixed vocabulary yet — phase 5 hasn't defined any scoring rules to
    # enumerate. See Decision 6 in this task file. Plain TextField;
    # choices/CheckConstraint can follow later without a type change.
    reason = models.TextField()
    flagged_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["listing", "baseline_pricepoint"], name="dealflag_listing_baseline_unique"
            ),
        ]

    def __str__(self):
        return f"DealFlag #{self.pk} ({self.score})"
