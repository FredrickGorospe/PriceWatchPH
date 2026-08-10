from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET
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
    OutcomeOperationResultSerializer,
    OutcomeStateSerializer,
    PricePointSerializer,
    PurchaseEvidenceRequestSerializer,
    ReviewListingSerializer,
    SaleEvidenceRequestSerializer,
    SkipOutcomeRequestSerializer,
    SkuSerializer,
)
from catalogue.models import Sku
from listings import review_services
from listings.models import Listing
from outcomes import outcome_services
from pricing.models import DealFlag, PricePoint


class Task023ReadView:
    permission_classes = (IsAuthenticated, StaffModelViewPermissions)
    required_model_permissions = ()


class SkuListView(Task023ReadView, generics.ListAPIView):
    queryset = Sku.objects.order_by("brand", "model", "variant", "id")
    serializer_class = SkuSerializer
    pagination_class = FixedPageNumberPagination
    required_model_permissions = ("catalogue.view_sku",)

    def get_queryset(self):
        queryset = super().get_queryset()
        if "q" not in self.request.query_params:
            return queryset

        query = self.request.query_params.get("q", "").strip()
        if not 2 <= len(query) <= 100:
            raise ValidationError({"q": "Must contain 2 through 100 characters."})
        return queryset.filter(
            Q(brand__icontains=query)
            | Q(model__icontains=query)
            | Q(variant__icontains=query)
        )


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


class ReviewListingReadView(Task023ReadView):
    serializer_class = ReviewListingSerializer
    required_model_permissions = ("listings.change_listing",)
    http_method_names = ("get",)


class ReviewListingListView(ReviewListingReadView, generics.ListAPIView):
    pagination_class = FixedPageNumberPagination

    def get_queryset(self):
        return (
            Listing.objects.filter(
                sku__isnull=True,
                reviewed_unresolved_at__isnull=True,
            )
            .select_related("raw_listing", "raw_listing__source", "sku")
            .annotate(
                review_evidence_at=Coalesce(
                    "raw_listing__occurred_at",
                    "raw_listing__fetched_at",
                )
            )
            .order_by("review_evidence_at", "pk")
        )


class ReviewListingDetailView(ReviewListingReadView, generics.RetrieveAPIView):
    queryset = Listing.objects.select_related(
        "raw_listing",
        "raw_listing__source",
        "sku",
    )

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except Listing.DoesNotExist:
            return Response(
                {"code": "listing_not_found", "detail": "Listing not found."},
                status=HTTP_404_NOT_FOUND,
            )

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs["pk"])
        except Listing.DoesNotExist:
            # Keep the missing response stable without exposing queryset details.
            raise


@csrf_protect
@require_GET
@never_cache
def session_csrf(request):
    return JsonResponse({"csrf_token": get_token(request)})


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


class DealFlagOutcomeBaseView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)
    parser_classes = (JSONParser,)

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
        if isinstance(error, outcome_services.OutcomePermissionDenied):
            response_status = HTTP_403_FORBIDDEN
        elif isinstance(error, outcome_services.OutcomeNotFound):
            response_status = HTTP_404_NOT_FOUND
        elif isinstance(error, outcome_services.OutcomeValidationError):
            response_status = HTTP_400_BAD_REQUEST
        else:
            response_status = HTTP_409_CONFLICT
        return Response(
            {"code": error.code, "detail": error.detail},
            status=response_status,
        )


class DealFlagOutcomeDetailView(DealFlagOutcomeBaseView):
    http_method_names = ("get",)

    def get(self, request, pk):
        try:
            state = outcome_services.get_outcome_state(
                actor=request.user,
                deal_flag_id=pk,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeStateSerializer(state).data, status=HTTP_200_OK)


class OutcomeMutationView(DealFlagOutcomeBaseView):
    http_method_names = ("post",)


class OutcomeSkipView(OutcomeMutationView):
    def post(self, request, pk):
        serializer = SkipOutcomeRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = outcome_services.skip(
                actor=request.user,
                deal_flag_id=pk,
                **serializer.validated_data,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeOperationResultSerializer(result).data, status=HTTP_200_OK)


class OutcomeRecordPurchaseView(OutcomeMutationView):
    def post(self, request, pk):
        serializer = PurchaseEvidenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = outcome_services.record_purchase(
                actor=request.user,
                deal_flag_id=pk,
                **serializer.validated_data,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeOperationResultSerializer(result).data, status=HTTP_200_OK)


class OutcomeRecordSaleView(OutcomeMutationView):
    def post(self, request, pk):
        serializer = SaleEvidenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = outcome_services.record_sale(
                actor=request.user,
                deal_flag_id=pk,
                **serializer.validated_data,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeOperationResultSerializer(result).data, status=HTTP_200_OK)


class OutcomeCorrectPurchaseView(OutcomeMutationView):
    def post(self, request, pk):
        serializer = PurchaseEvidenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = outcome_services.correct_purchase(
                actor=request.user,
                deal_flag_id=pk,
                **serializer.validated_data,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeOperationResultSerializer(result).data, status=HTTP_200_OK)


class OutcomeCorrectSaleView(OutcomeMutationView):
    def post(self, request, pk):
        serializer = SaleEvidenceRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return self.invalid_request(serializer.errors)

        try:
            result = outcome_services.correct_sale(
                actor=request.user,
                deal_flag_id=pk,
                **serializer.validated_data,
            )
        except (
            outcome_services.OutcomePermissionDenied,
            outcome_services.OutcomeNotFound,
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            return self.service_error(error)

        return Response(OutcomeOperationResultSerializer(result).data, status=HTTP_200_OK)
