from django.db import models
from django.db.models import Q


class Source(models.Model):
    name = models.CharField(max_length=100, unique=True)
    base_url = models.TextField(blank=True, default="")
    terms_notes = models.TextField()
    # Null means "no automated fetching cadence exists to describe" — not
    # unlimited and not merely unset. docs/00_PLANNING.md never marked this
    # field nullable; that was a gap in the spec, closed here, not a
    # violation of it. See Decision 1 in this task file.
    rate_limit = models.PositiveIntegerField(null=True, blank=True)
    last_successful_fetch = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(rate_limit__gt=0),
                name="source_rate_limit_positive",
            ),
            models.CheckConstraint(
                condition=~Q(terms_notes=""),
                name="source_terms_notes_not_blank",
            ),
        ]

    def __str__(self):
        return self.name
