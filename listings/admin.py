from django import forms
from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseNotAllowed, HttpResponseRedirect
from django.urls import path, reverse

from catalogue.models import Sku, SkuAlias
from listings import review_services
from listings.models import Listing
from listings.normalisation import normalise_title


class ReviewScopeFilter(admin.SimpleListFilter):
    title = "review scope"
    parameter_name = "review_scope"

    def lookups(self, request, model_admin):
        return (("all", "All listings"),)

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset

        # Keep integrity exceptions visible so a human can repair their SKU.
        return queryset.filter(sku__isnull=True, reviewed_unresolved_at__isnull=True)


class ListingConfirmationForm(forms.ModelForm):
    sku = forms.ModelChoiceField(
        queryset=Sku.objects.all(),
        required=True,
        label="Confirm or correct SKU",
    )
    create_alias = forms.BooleanField(
        required=False,
        initial=False,
        label="Create exact alias from this raw title",
    )

    class Meta:
        model = Listing
        fields = ("sku", "create_alias")

    def clean(self):
        cleaned_data = super().clean()
        sku = cleaned_data.get("sku")
        if not cleaned_data.get("create_alias") or sku is None:
            return cleaned_data

        normalised_text = normalise_title(self.instance.raw_listing.raw_title)
        existing_alias = SkuAlias.objects.filter(
            normalised_text=normalised_text,
        ).first()
        if existing_alias is not None and existing_alias.sku_id != sku.pk:
            self.add_error(
                "create_alias",
                "This normalized title is already an alias for a different SKU.",
            )

        return cleaned_data


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    form = ListingConfirmationForm
    change_form_template = "admin/listings/listing/change_form.html"
    actions = None
    list_display = (
        "id",
        "raw_title",
        "current_sku",
        "resolution_method",
        "resolution_confidence",
        "reviewed_unresolved_at",
    )
    list_filter = (ReviewScopeFilter,)
    search_fields = (
        "raw_listing__raw_title",
        "raw_listing__external_id",
    )
    fieldsets = (
        (
            "Confirmation",
            {"fields": ("sku", "create_alias")},
        ),
        (
            "RawListing evidence",
            {
                "fields": (
                    "raw_listing_pk",
                    "raw_external_id",
                    "raw_title",
                    "normalised_raw_title",
                    "raw_price_text",
                    "raw_price",
                    "raw_source",
                    "raw_url",
                    "raw_seller",
                    "raw_fetched_at",
                    "raw_occurred_at",
                    "raw_payload",
                )
            },
        ),
        (
            "Listing evidence",
            {
                "fields": (
                    "current_sku",
                    "current_sku_brand",
                    "current_sku_model",
                    "current_sku_variant",
                    "current_sku_category",
                    "condition",
                    "resolution_method",
                    "resolution_confidence",
                    "resolved_at",
                    "reviewed_unresolved_at",
                    "observed_at",
                    "price",
                    "location",
                    "price_kind",
                    "trade_side",
                )
            },
        ),
    )
    readonly_fields = (
        "raw_listing_pk",
        "raw_external_id",
        "raw_title",
        "normalised_raw_title",
        "raw_price_text",
        "raw_price",
        "raw_source",
        "raw_url",
        "raw_seller",
        "raw_fetched_at",
        "raw_occurred_at",
        "raw_payload",
        "current_sku",
        "current_sku_brand",
        "current_sku_model",
        "current_sku_variant",
        "current_sku_category",
        "condition",
        "resolution_method",
        "resolution_confidence",
        "resolved_at",
        "reviewed_unresolved_at",
        "observed_at",
        "price",
        "location",
        "price_kind",
        "trade_side",
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            "raw_listing",
            "raw_listing__source",
            "sku",
        )
        # Source observation time is authoritative even for historical derived rows.
        return queryset.order_by(
            Coalesce("raw_listing__occurred_at", "raw_listing__fetched_at").asc(),
            "pk",
        )

    def get_urls(self):
        custom_urls = [
            path(
                "<path:object_id>/mark-reviewed-unresolved/",
                self.admin_site.admin_view(self.mark_reviewed_unresolved_view),
                name="listings_listing_mark_reviewed_unresolved",
            ),
        ]
        return custom_urls + super().get_urls()

    def render_change_form(
        self,
        request,
        context,
        add=False,
        change=False,
        form_url="",
        obj=None,
    ):
        context["can_mark_reviewed_unresolved"] = (
            change
            and obj is not None
            and self.has_change_permission(request, obj)
            and self._is_reviewable_unresolved(obj)
        )
        if context["can_mark_reviewed_unresolved"]:
            context["mark_reviewed_unresolved_url"] = reverse(
                "admin:listings_listing_mark_reviewed_unresolved",
                args=[obj.pk],
            )
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def mark_reviewed_unresolved_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        try:
            result = review_services.mark_reviewed_unresolved(
                actor=request.user,
                listing_id=int(unquote(object_id)),
                audit_writer=lambda listing, change_message: self.log_change(
                    request,
                    listing,
                    change_message,
                ),
            )
        except review_services.ReviewPermissionDenied as error:
            raise PermissionDenied from error
        except review_services.ReviewNotFound as error:
            raise Http404(error.detail) from error
        except review_services.ReviewConflict:
            self.message_user(
                request,
                "This listing is not eligible to be marked reviewed unresolved.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(
                reverse(
                    "admin:listings_listing_change",
                    args=[unquote(object_id)],
                )
            )

        self.message_user(request, "Listing marked reviewed unresolved.")
        return HttpResponseRedirect(
            reverse("admin:listings_listing_change", args=[result.listing_id])
        )

    def save_model(self, request, obj, form, change):
        result = review_services.confirm_listing_sku(
            actor=request.user,
            listing_id=obj.pk,
            sku_id=form.cleaned_data["sku"].pk,
            create_alias=form.cleaned_data["create_alias"],
            audit_writer=lambda listing, change_message: self.log_change(
                request,
                listing,
                change_message,
            ),
        )
        obj.sku_id = result.sku_id
        obj.resolution_method = result.resolution_method
        obj.resolution_confidence = result.resolution_confidence
        obj.resolved_at = result.resolved_at
        obj.reviewed_unresolved_at = result.reviewed_unresolved_at
        # ModelAdmin logs after save_model, so suppress only that duplicate hook.
        request._listing_review_service_log_pending = True

    def log_change(self, request, obj, message):
        if getattr(request, "_listing_review_service_log_pending", False):
            del request._listing_review_service_log_pending
            return None
        return super().log_change(request, obj, message)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        create_alias = ListingConfirmationForm.base_fields[
            "create_alias"
        ].to_python(request.POST.get("create_alias"))
        if (
            request.method == "POST"
            and create_alias
            and not request.user.has_perm("catalogue.add_skualias")
        ):
            raise PermissionDenied

        return super().changeform_view(
            request,
            object_id=object_id,
            form_url=form_url,
            extra_context=extra_context,
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @staticmethod
    def _is_reviewable_unresolved(listing):
        return (
            listing.sku_id is None
            and listing.resolution_method in {"unresolved", "fuzzy_match"}
        )

    @admin.display(description="RawListing ID", ordering="raw_listing__pk")
    def raw_listing_pk(self, obj):
        return obj.raw_listing_id

    @admin.display(description="External ID")
    def raw_external_id(self, obj):
        return obj.raw_listing.external_id

    @admin.display(description="Raw title", ordering="raw_listing__raw_title")
    def raw_title(self, obj):
        return obj.raw_listing.raw_title

    @admin.display(description="Normalised title")
    def normalised_raw_title(self, obj):
        return normalise_title(obj.raw_listing.raw_title)

    @admin.display(description="Raw price text")
    def raw_price_text(self, obj):
        return obj.raw_listing.raw_price_text

    @admin.display(description="Raw price")
    def raw_price(self, obj):
        return obj.raw_listing.raw_price

    @admin.display(description="Source")
    def raw_source(self, obj):
        return obj.raw_listing.source

    @admin.display(description="URL")
    def raw_url(self, obj):
        return obj.raw_listing.url

    @admin.display(description="Seller")
    def raw_seller(self, obj):
        return obj.raw_listing.seller

    @admin.display(description="Fetched at")
    def raw_fetched_at(self, obj):
        return obj.raw_listing.fetched_at

    @admin.display(description="Occurred at")
    def raw_occurred_at(self, obj):
        return obj.raw_listing.occurred_at

    @admin.display(description="Payload")
    def raw_payload(self, obj):
        return obj.raw_listing.payload

    @admin.display(description="Current SKU", ordering="sku")
    def current_sku(self, obj):
        return obj.sku

    @admin.display(description="SKU brand", ordering="sku__brand")
    def current_sku_brand(self, obj):
        return obj.sku.brand if obj.sku else None

    @admin.display(description="SKU model", ordering="sku__model")
    def current_sku_model(self, obj):
        return obj.sku.model if obj.sku else None

    @admin.display(description="SKU variant", ordering="sku__variant")
    def current_sku_variant(self, obj):
        return obj.sku.variant if obj.sku else None

    @admin.display(description="SKU category", ordering="sku__category")
    def current_sku_category(self, obj):
        return obj.sku.get_category_display() if obj.sku else None
