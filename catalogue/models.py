from django.db import models
from django.db.models import Q

# Module-level, not a class attribute of Sku — a name referenced inside
# Meta's own class body can't see Sku's namespace, only the enclosing
# module's.
CATEGORY_CHOICES = [
    ("gpu", "GPU"),
    ("cpu", "CPU"),
    ("ram", "RAM"),
    ("mobo", "Motherboard"),
    ("monitor", "Monitor"),
    ("peripheral", "Peripheral"),
]


class Sku(models.Model):
    brand = models.CharField(max_length=100)
    model = models.CharField(max_length=200)
    # Non-null empty string, not NULL — NULLs don't collide in Postgres, so a
    # NULL variant would let the (brand, model, variant) unique index be
    # bypassed by concurrent creates of "the same" SKU. See
    # docs/00_PLANNING.md §2.
    variant = models.CharField(max_length=200, blank=True, default="")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    launch_msrp = models.DecimalField(max_digits=12, decimal_places=2)
    launch_date = models.DateField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "model", "variant"],
                name="sku_brand_model_variant_unique",
            ),
            models.CheckConstraint(
                condition=Q(launch_msrp__gte=0),
                name="sku_launch_msrp_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(category__in=[c[0] for c in CATEGORY_CHOICES]),
                name="sku_category_in_vocabulary",
            ),
        ]

    def __str__(self):
        return f"{self.brand} {self.model} {self.variant}".strip()


SOURCE_OF_TRUTH_CHOICES = [
    ("human_confirmed", "Human confirmed"),
    ("seed", "Seed"),
]


class SkuAlias(models.Model):
    sku = models.ForeignKey(Sku, on_delete=models.CASCADE, related_name="aliases")
    alias_text = models.TextField()
    normalised_text = models.TextField(unique=True)
    source_of_truth = models.CharField(max_length=20, choices=SOURCE_OF_TRUTH_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(source_of_truth__in=[c[0] for c in SOURCE_OF_TRUTH_CHOICES]),
                name="skualias_source_of_truth_in_vocabulary",
            ),
        ]

    def __str__(self):
        return self.alias_text
