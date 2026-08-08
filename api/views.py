from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from api.pagination import FixedPageNumberPagination
from api.permissions import StaffModelViewPermissions
from api.serializers import (
    DealFlagSerializer,
    ListingSerializer,
    PricePointSerializer,
    SkuSerializer,
)
from catalogue.models import Sku
from listings.models import Listing
from pricing.models import DealFlag, PricePoint


class Task023ReadView:
    permission_classes = (IsAuthenticated, StaffModelViewPermissions)
    required_model_permissions = ()


class SkuListView(Task023ReadView, generics.ListAPIView):
    queryset = Sku.objects.order_by("brand", "model", "variant", "id")
    serializer_class = SkuSerializer
    pagination_class = FixedPageNumberPagination
    required_model_permissions = ("catalogue.view_sku",)


class SkuDetailView(Task023ReadView, generics.RetrieveAPIView):
    queryset = Sku.objects.all()
    serializer_class = SkuSerializer
    required_model_permissions = ("catalogue.view_sku",)


class ListingDetailView(Task023ReadView, generics.RetrieveAPIView):
    queryset = Listing.objects.all()
    serializer_class = ListingSerializer
    required_model_permissions = ("listings.view_listing",)


class SkuPricePointListView(Task023ReadView, generics.ListAPIView):
    serializer_class = PricePointSerializer
    pagination_class = FixedPageNumberPagination
    required_model_permissions = (
        "catalogue.view_sku",
        "pricing.view_pricepoint",
    )
    valid_conditions = {"new", "like_new", "used", "for_parts"}

    def get_queryset(self):
        sku = get_object_or_404(
            Sku.objects.only("pk"),
            pk=self.kwargs["sku_pk"],
        )
        queryset = PricePoint.objects.filter(sku_id=sku.pk)
        condition = self.request.query_params.get("condition")
        if condition is not None:
            if condition not in self.valid_conditions:
                raise ValidationError(
                    {"condition": "Must be new, like_new, used, or for_parts."}
                )
            queryset = queryset.filter(condition=condition)
        return queryset.order_by("day", "condition", "id")


class DealFlagListView(Task023ReadView, generics.ListAPIView):
    queryset = DealFlag.objects.select_related(
        "listing",
        "baseline_pricepoint",
        "baseline_pricepoint__sku",
    ).order_by("-flagged_at", "id")
    serializer_class = DealFlagSerializer
    pagination_class = FixedPageNumberPagination
    required_model_permissions = (
        "catalogue.view_sku",
        "listings.view_listing",
        "pricing.view_pricepoint",
        "pricing.view_dealflag",
    )
