from django.urls import path

from api import views

app_name = "api-v1"

urlpatterns = [
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
]
