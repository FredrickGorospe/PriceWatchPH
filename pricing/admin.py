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
    pass


@admin.register(DealFlag)
class DealFlagAdmin(ReadOnlyEvidenceAdmin):
    pass
