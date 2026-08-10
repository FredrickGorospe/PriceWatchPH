from django.urls import path

from api import views

app_name = "api-v1"

urlpatterns = [
    path("session/csrf/", views.session_csrf, name="session-csrf"),
    path(
        "reviews/listings/",
        views.ReviewListingListView.as_view(),
        name="review-listing-list",
    ),
    path(
        "reviews/listings/<int:pk>/",
        views.ReviewListingDetailView.as_view(),
        name="review-listing-detail",
    ),
    path(
        "reviews/listings/<int:pk>/mark-reviewed-unresolved/",
        views.MarkReviewedUnresolvedView.as_view(),
        name="review-mark-reviewed-unresolved",
    ),
    path(
        "reviews/listings/<int:pk>/confirm-sku/",
        views.ConfirmSkuView.as_view(),
        name="review-confirm-sku",
    ),
    path("skus/", views.SkuListView.as_view(), name="sku-list"),
    path("skus/<int:pk>/", views.SkuDetailView.as_view(), name="sku-detail"),
    path(
        "skus/<int:sku_pk>/price-points/",
        views.SkuPricePointListView.as_view(),
        name="sku-pricepoint-list",
    ),
    path(
        "listings/<int:pk>/",
        views.ListingDetailView.as_view(),
        name="listing-detail",
    ),
    path("deal-flags/", views.DealFlagListView.as_view(), name="dealflag-list"),
    path(
        "deal-flags/<int:pk>/outcome/",
        views.DealFlagOutcomeDetailView.as_view(),
        name="dealflag-outcome-detail",
    ),
    path(
        "deal-flags/<int:pk>/outcome/skip/",
        views.OutcomeSkipView.as_view(),
        name="dealflag-outcome-skip",
    ),
    path(
        "deal-flags/<int:pk>/outcome/record-purchase/",
        views.OutcomeRecordPurchaseView.as_view(),
        name="dealflag-outcome-record-purchase",
    ),
    path(
        "deal-flags/<int:pk>/outcome/record-sale/",
        views.OutcomeRecordSaleView.as_view(),
        name="dealflag-outcome-record-sale",
    ),
    path(
        "deal-flags/<int:pk>/outcome/correct-purchase/",
        views.OutcomeCorrectPurchaseView.as_view(),
        name="dealflag-outcome-correct-purchase",
    ),
    path(
        "deal-flags/<int:pk>/outcome/correct-sale/",
        views.OutcomeCorrectSaleView.as_view(),
        name="dealflag-outcome-correct-sale",
    ),
]
