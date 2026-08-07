from django.contrib import admin
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from ingestion.forms import LogPersonalTradeForm
from ingestion.models import RawListing, Swap
from ingestion.pseudonymise import pseudonymise
from ingestion.timeparse import manila_midnight
from sources.models import Source


def _trade_payload(side, condition):
    payload = {"stated_trade_side": side}
    if condition:
        payload["stated_condition"] = condition
    return payload


def _create_personal_rawlisting(
    *,
    source,
    title,
    price_text,
    price,
    seller,
    fetched_at,
    occurred_at,
    side,
    condition,
):
    return RawListing.objects.create(
        source=source,
        raw_title=title,
        raw_price_text=price_text,
        raw_price=price,
        # A first-party personal record has no external listing URL.
        url="",
        seller=seller,
        fetched_at=fetched_at,
        occurred_at=occurred_at,
        external_id=None,
        payload=_trade_payload(side, condition),
    )


@admin.register(RawListing)
class RawListingAdmin(admin.ModelAdmin):
    change_list_template = "admin/ingestion/rawlisting/change_list.html"

    def get_urls(self):
        custom_urls = [
            path(
                "log-personal-trade/",
                self.admin_site.admin_view(self.log_personal_trade_view),
                name="ingestion_rawlisting_log_personal_trade",
            ),
        ]
        return custom_urls + super().get_urls()

    def log_personal_trade_view(self, request):
        if request.method == "POST":
            form = LogPersonalTradeForm(request.POST)
            if form.is_valid():
                self._write_personal_trade(form.cleaned_data)
                self.message_user(request, "Personal trade logged.")
                return HttpResponseRedirect(
                    reverse("admin:ingestion_rawlisting_changelist")
                )
        else:
            form = LogPersonalTradeForm()

        context = {
            **self.admin_site.each_context(request),
            "form": form,
            "opts": self.model._meta,
            "title": "Log a personal trade",
        }
        return TemplateResponse(
            request,
            "admin/ingestion/rawlisting/log_personal_trade.html",
            context,
        )

    @staticmethod
    def _write_personal_trade(data):
        # A swap must never leave one immutable side behind if a later write fails.
        with transaction.atomic():
            source = Source.objects.get(name="personal_records")
            occurred_at = manila_midnight(data["occurred_on"])
            fetched_at = timezone.now()
            counterparty = data["counterparty"]
            seller = pseudonymise(counterparty) if counterparty else ""

            if data["trade_type"] in {"buy", "sell"}:
                _create_personal_rawlisting(
                    source=source,
                    title=data["item"],
                    price_text=data["price_text"],
                    price=data["price"],
                    seller=seller,
                    fetched_at=fetched_at,
                    occurred_at=occurred_at,
                    side=data["trade_type"],
                    condition=data["condition"],
                )
                return

            given_listing = _create_personal_rawlisting(
                source=source,
                title=data["given_item"],
                price_text=data["given_value_text"],
                price=data["given_value"],
                seller=seller,
                fetched_at=fetched_at,
                occurred_at=occurred_at,
                side="sell",
                condition=data["given_condition"],
            )
            received_listing = _create_personal_rawlisting(
                source=source,
                title=data["received_item"],
                price_text=data["received_value_text"],
                price=data["received_value"],
                seller=seller,
                fetched_at=fetched_at,
                occurred_at=occurred_at,
                side="buy",
                condition=data["received_condition"],
            )
            Swap.objects.create(
                given_listing=given_listing,
                received_listing=received_listing,
                cash_adjustment=data["cash_adjustment"],
            )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # Django otherwise turns a blocked change form into a read-only object view.
        if obj is not None:
            return False
        return super().has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Swap)
class SwapAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "given_listing",
        "received_listing",
        "cash_adjustment",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
