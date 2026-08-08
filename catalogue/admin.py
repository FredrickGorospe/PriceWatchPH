from django.contrib import admin

from catalogue.models import Sku, SkuAlias
from listings.models import Listing
from listings.normalisation import normalise_title


@admin.register(Sku)
class SkuAdmin(admin.ModelAdmin):
    def get_deleted_objects(self, objs, request):
        skus = list(objs)
        deleted_objects, model_count, perms_needed, protected = (
            super().get_deleted_objects(skus, request)
        )
        listing_references = Listing.objects.filter(sku__in=skus)
        alias_references = SkuAlias.objects.filter(sku__in=skus)
        # SET_NULL and CASCADE would silently invalidate persisted catalogue evidence.
        protected.extend(str(listing) for listing in listing_references)
        protected.extend(str(alias) for alias in alias_references)
        return deleted_objects, model_count, perms_needed, protected


@admin.register(SkuAlias)
class SkuAliasAdmin(admin.ModelAdmin):
    fields = (
        "sku",
        "alias_text",
        "normalised_text",
        "source_of_truth",
        "created_at",
    )
    readonly_fields = fields
    list_display = (
        "alias_text",
        "normalised_text",
        "sku",
        "source_of_truth",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_deleted_objects(self, objs, request):
        aliases = list(objs)
        deleted_objects, model_count, perms_needed, protected = (
            super().get_deleted_objects(aliases, request)
        )
        alias_keys = {
            (alias.sku_id, alias.normalised_text)
            for alias in aliases
        }
        exact_alias_listings = Listing.objects.filter(
            sku_id__in={sku_id for sku_id, _ in alias_keys},
            resolution_method="exact_alias",
        ).select_related("raw_listing")
        supporting_listings = (
            listing
            for listing in exact_alias_listings
            if (
                listing.sku_id,
                normalise_title(listing.raw_listing.raw_title),
            )
            in alias_keys
        )
        # Machine-derived exact matches must retain the exact evidence they cite.
        protected.extend(str(listing) for listing in supporting_listings)
        return deleted_objects, model_count, perms_needed, protected
