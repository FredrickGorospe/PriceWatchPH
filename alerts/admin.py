"""Read-only admin visibility for durable alert delivery claims.

TASK_033 answers one operational question — "was this deal flag claimed, when,
did it send, and did it fail" — and makes a stuck `pending` row visible
(docs/07_PLANNING.md §11, §12). It adds no behavior, no network call, and no
mutation path.

Deliberately no action, view, URL, or template that could trigger or resend a
send: docs/07_PLANNING.md §12 rules that out as a second, less-auditable
invocation path alongside the send_deal_alerts command.
"""

from django.contrib import admin

from alerts.models import AlertDelivery
from pricing.admin import ReadOnlyEvidenceAdmin


@admin.register(AlertDelivery)
class AlertDeliveryAdmin(ReadOnlyEvidenceAdmin):
    list_display = (
        "deal_flag",
        "status",
        "claimed_at",
        "terminal_at",
        "failure_detail",
    )
    # Status is the diagnostic axis: it is what makes a stuck `pending` row
    # findable among sent and failed ones. TASK_030 fixes the vocabulary at
    # three values, so this filter cannot grow unbounded.
    list_filter = ("status",)
    # Stops at deal_flag on purpose. list_display renders it, so without this
    # the changelist issues a query per row — but traversing further, to
    # listing/sku/raw_listing/source, would pull RawListing and Source evidence
    # into the alert path that Phase 7 keeps it out of.
    list_select_related = ("deal_flag",)
    ordering = ("-claimed_at", "pk")
