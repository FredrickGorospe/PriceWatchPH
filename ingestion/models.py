from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from sources.models import Source


class RawListing(models.Model):
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="raw_listings")
    raw_title = models.TextField()
    # Verbatim string as fetched — always populated, even when raw_price
    # parses cleanly, since raw_title's "verbatim" rule applies to price too.
    raw_price_text = models.TextField()
    # Null when raw_price_text could not be parsed to a Decimal (e.g. "PM for
    # price", a range, a typo). The row is immutable and can never be fixed
    # afterward, so an unparseable price is preserved as a fact, not dropped.
    # See Decision 1 in this task file.
    raw_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    url = models.TextField()
    seller = models.TextField()
    fetched_at = models.DateTimeField()
    # When the source stated the priced event happened — the transaction date
    # for personal_records, a posting date if a scraped listing shows one.
    # Distinct from fetched_at (when this system learned it); nullable
    # because most sources state no such date. See TASK_005 Decision 2.
    occurred_at = models.DateTimeField(null=True, blank=True)
    external_id = models.CharField(max_length=200, null=True, blank=True)
    # The verbatim source row, so a fact this schema did not anticipate is
    # recoverable rather than lost when the source file is edited or
    # discarded. NULL means no payload was recorded; {} means one was
    # recorded and was empty — the two are different facts and must stay
    # distinguishable. Any counterparty name inside must already be
    # pseudonymised before write — see ingestion.pseudonymise.redact_payload.
    # See TASK_005 Decisions 1 and 5.
    payload = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "external_id", "fetched_at"],
                condition=Q(external_id__isnull=False),
                name="rawlisting_source_external_id_fetched_at_unique",
            ),
            models.CheckConstraint(
                condition=Q(raw_price__gte=0),
                name="rawlisting_raw_price_non_negative",
            ),
        ]

    def __str__(self):
        return self.raw_title

    def save(self, *args, **kwargs):
        # Option A from docs/00_PLANNING.md §3: catches the realistic everyday
        # mistake (load, edit, save) with a readable error. The database
        # trigger (0002) is the real enforcement — this does not catch
        # QuerySet.update() or raw SQL, and is not meant to.
        if self.pk is not None:
            raise ValidationError("RawListing is immutable and cannot be updated after creation.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("RawListing is immutable and cannot be deleted.")


class Swap(models.Model):
    given_listing = models.OneToOneField(
        RawListing,
        on_delete=models.PROTECT,
        related_name="swap_given",
    )
    received_listing = models.OneToOneField(
        RawListing,
        on_delete=models.PROTECT,
        related_name="swap_received",
    )
    cash_adjustment = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
