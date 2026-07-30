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
    external_id = models.CharField(max_length=200, null=True, blank=True)

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
