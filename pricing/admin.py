from django.contrib import admin

from pricing.models import DealFlag, PricePoint


class ReadOnlyEvidenceAdmin(admin.ModelAdmin):
    actions = None

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PricePoint)
class PricePointAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "sku",
        "condition",
        "day",
        "median",
        "mad",
        "n_listings",
        "window_start_day",
        "window_end_day",
        "calculation_contract_version",
        "calculated_at",
    )
    list_filter = ("condition", "day", "calculation_contract_version")
    list_select_related = ("sku",)
    ordering = ("-day", "sku_id", "condition")


@admin.register(DealFlag)
class DealFlagAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "listing",
        "score",
        "baseline_pricepoint",
        "reason",
        "flagged_at",
    )
    list_filter = ("reason", "flagged_at")
    list_select_related = (
        "listing",
        "baseline_pricepoint",
        "baseline_pricepoint__sku",
    )
    ordering = ("-flagged_at", "pk")
