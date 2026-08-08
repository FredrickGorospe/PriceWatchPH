from django.contrib import admin

from catalogue.models import Sku, SkuAlias
from listings.models import Listing


@admin.register(Sku)
class SkuAdmin(admin.ModelAdmin):
    def get_deleted_objects(self, objs, request):
        deleted_objects, model_count, perms_needed, protected = (
            super().get_deleted_objects(objs, request)
        )
        human_confirmed_references = Listing.objects.filter(
            sku__in=objs,
            resolution_method="human_confirmed",
        )
        # SET_NULL is normally deletable, so surface confirmed decisions as protected.
        protected.extend(str(listing) for listing in human_confirmed_references)
        return deleted_objects, model_count, perms_needed, protected


admin.site.register(SkuAlias)
