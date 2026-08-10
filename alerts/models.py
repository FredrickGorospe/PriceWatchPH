from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from pricing.models import DealFlag

ALERT_DELIVERY_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("sent", "Sent"),
    ("failed", "Failed"),
]


class AlertDelivery(models.Model):
    # The claim's identity. One durable claim per DealFlag, and it can never
    # move to another DealFlag (see the task030_lifecycle_guard trigger).
    deal_flag = models.OneToOneField(DealFlag, on_delete=models.PROTECT, related_name="alert_delivery")
    status = models.CharField(max_length=20, choices=ALERT_DELIVERY_STATUS_CHOICES)
    # Set explicitly by the claiming caller, before any network I/O — no
    # auto_now_add, matching DealFlag.flagged_at. Immutable after insert.
    claimed_at = models.DateTimeField()
    # Null exactly while pending; set once the row reaches sent/failed.
    terminal_at = models.DateTimeField(null=True, blank=True)
    # Sanitized, application-owned failure text only — never a raw transport
    # exception or request URL (docs/07_PLANNING.md §10.3).
    failure_detail = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=[c[0] for c in ALERT_DELIVERY_STATUS_CHOICES]),
                name="alertdelivery_status_in_vocabulary",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(status="pending") & Q(terminal_at__isnull=True))
                    | (Q(status__in=["sent", "failed"]) & Q(terminal_at__isnull=False))
                ),
                name="alertdelivery_terminal_at_matches_status",
            ),
            models.CheckConstraint(
                condition=(
                    (Q(status="failed") & Q(failure_detail__isnull=False) & ~Q(failure_detail=""))
                    | (Q(status__in=["pending", "sent"]) & Q(failure_detail__isnull=True))
                ),
                name="alertdelivery_failure_detail_matches_status",
            ),
            models.CheckConstraint(
                condition=Q(terminal_at__isnull=True) | Q(terminal_at__gte=F("claimed_at")),
                name="alertdelivery_terminal_at_not_before_claimed_at",
            ),
        ]

    def __str__(self):
        return f"AlertDelivery #{self.pk} ({self.status})"

    # No save() override: the approved pending -> sent|failed transition must
    # remain possible through ordinary ORM save(). The database trigger
    # (alerts_alertdelivery_task030_lifecycle_guard) is what actually enforces
    # the lifecycle against every path, including ones this method can't see.
    def delete(self, *args, **kwargs):
        raise ValidationError(
            "AlertDelivery cannot be deleted: it is the durable at-most-once alert claim."
        )
