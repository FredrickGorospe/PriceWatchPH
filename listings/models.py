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
]


class Listing(models.Model):
    raw_listing = models.OneToOneField(RawListing, on_delete=models.PROTECT, related_name="listing")
    sku = models.ForeignKey(Sku, null=True, blank=True, on_delete=models.SET_NULL, related_name="listings")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES)
    location = models.TextField()
    resolution_confidence = models.DecimalField(max_digits=5, decimal_places=4)
    resolution_method = models.CharField(max_length=20, choices=RESOLUTION_METHOD_CHOICES)
    resolved_at = models.DateTimeField()

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
        ]

    def __str__(self):
        return f"Listing #{self.pk} ({self.condition})"
