from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)
from rest_framework.views import APIView

from api.pagination import FixedPageNumberPagination
from api.permissions import StaffModelViewPermissions
from api.serializers import (
    ConfirmSkuRequestSerializer,
    ConfirmSkuResponseSerializer,
    DealFlagSerializer,
    ListingSerializer,
    MarkReviewedUnresolvedRequestSerializer,
    MarkReviewedUnresolvedResponseSerializer,
    PricePointSerializer,
    SkuSerializer,
)
from catalogue.models import Sku
from listings import review_services
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


class ReviewMutationView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)
    http_method_names = ("post",)

    @staticmethod
    def invalid_request(errors):
        return Response(
            {
                "code": "invalid_request",
                "detail": "Request validation failed.",
                "errors": errors,
            },
            status=HTTP_400_BAD_REQUEST,
        )

    @staticmethod
    def service_error(error):
        if isinstance(error, review_services.ReviewPermissionDenied):
            response_status = HTTP_403_FORBIDDEN
        elif isinstance(error, review_services.ReviewNotFound):
            response_status = HTTP_404_NOT_FOUND
        else:
            response_status = HTTP_409_CONFLICT
        return Response(
            {"code": error.code, "detail": error.detail},
            status=response_status,
        )


class MarkReviewedUnresolvedView(ReviewMutationView):
    def post(self, request, pk):
        serializer = MarkReviewedUnresolvedRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = review_services.mark_reviewed_unresolved(
                actor=request.user,
                listing_id=pk,
            )
        except (
            review_services.ReviewPermissionDenied,
            review_services.ReviewNotFound,
            review_services.ReviewConflict,
        ) as error:
            return self.service_error(error)

        response = MarkReviewedUnresolvedResponseSerializer(result)
        return Response(response.data, status=HTTP_200_OK)


class ConfirmSkuView(ReviewMutationView):
    def post(self, request, pk):
        serializer = ConfirmSkuRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = review_services.confirm_listing_sku(
                actor=request.user,
                listing_id=pk,
                **serializer.validated_data,
            )
        except (
            review_services.ReviewPermissionDenied,
            review_services.ReviewNotFound,
            review_services.ReviewConflict,
        ) as error:
            return self.service_error(error)

        response = ConfirmSkuResponseSerializer(result)
        return Response(response.data, status=HTTP_200_OK)
