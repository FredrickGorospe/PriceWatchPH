from django.db import models
from django.db.models import F, Q

from pricing.models import DealFlag


class Outcome(models.Model):
    deal_flag = models.OneToOneField(DealFlag, on_delete=models.PROTECT, related_name="outcome")
    acted = models.BooleanField()
    skip_reason = models.TextField(null=True, blank=True)
    bought_at = models.DateTimeField(null=True, blank=True)
    bought_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    sold_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    days_held = models.PositiveIntegerField(null=True, blank=True)
    # Database-computed, not entered directly (see Decision 1) — verified
    # against this repo's actual Django 5.2.16 + Postgres 16 that
    # GeneratedField(db_persist=True) here: propagates NULL correctly when
    # either price is missing, is rejected as an UPDATE target by Postgres
    # itself, and is silently excluded (not errored) by Django's ORM if a
    # caller tries to set it directly. Signed: losses are the most
    # informative rows and must be storable.
    realised_margin = models.GeneratedField(
        expression=F("sold_price") - F("bought_price"),
        output_field=models.DecimalField(max_digits=12, decimal_places=2),
        db_persist=True,
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(acted=True) | (Q(skip_reason__isnull=False) & ~Q(skip_reason="")),
                name="outcome_skip_reason_required_when_not_acted",
            ),
            models.CheckConstraint(condition=Q(days_held__gte=0), name="outcome_days_held_non_negative"),
        ]

    def __str__(self):
        return f"Outcome #{self.pk} (acted={self.acted})"
