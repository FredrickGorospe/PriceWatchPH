from decimal import Decimal, InvalidOperation

from django.contrib import admin, messages
from django.contrib.admin.models import ADDITION
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect
from django.template import engines
from django.urls import path, reverse
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_datetime

from outcomes import outcome_services
from outcomes.models import Outcome
from pricing.models import DealFlag


# Rendered via an inline template rather than a template file, keeping the
# governed admin surface entirely inside this authorized file. Extending
# admin/base_site.html gets standard admin chrome from self.admin_site.each_context.
_UNTRACKED_TEMPLATE_SOURCE = """
{% extends "admin/base_site.html" %}
{% block content %}
<h1>Deal flags without a recorded Outcome</h1>
<table>
  <thead><tr><th>Deal flag</th><th>Actions</th></tr></thead>
  <tbody>
  {% for deal_flag in deal_flags %}
    <tr>
      <td>{{ deal_flag.pk }} &mdash; {{ deal_flag }}</td>
      <td>
        <form action="{% url 'admin:outcomes_outcome_skip' deal_flag.pk %}" method="post" style="display:inline">
          {% csrf_token %}
          <input type="text" name="skip_reason" placeholder="Reason">
          <button type="submit">Skip</button>
        </form>
        <form action="{% url 'admin:outcomes_outcome_record_purchase' deal_flag.pk %}" method="post" style="display:inline">
          {% csrf_token %}
          <input type="text" name="bought_at" placeholder="Bought at (ISO 8601, explicit offset)">
          <input type="text" name="bought_price" placeholder="Bought price">
          <button type="submit">Record purchase</button>
        </form>
      </td>
    </tr>
  {% empty %}
    <tr><td colspan="2">No untracked deal flags.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
"""


def _parse_admin_datetime(raw):
    # A parse failure or naive input becomes None; the shared service's own
    # typed validation rejects it with a clean OutcomeValidationError rather
    # than this adapter guessing at a timezone.
    if not isinstance(raw, str):
        return None
    parsed = parse_datetime(raw)
    if parsed is None or django_timezone.is_naive(parsed):
        return None
    return parsed


def _parse_admin_decimal(raw):
    if not isinstance(raw, str):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


@admin.register(Outcome)
class OutcomeAdmin(admin.ModelAdmin):
    actions = None
    list_display = (
        "deal_flag",
        "acted",
        "skip_reason",
        "bought_at",
        "bought_price",
        "sold_at",
        "sold_price",
        "days_held",
        "realised_margin",
    )
    list_filter = ("acted",)
    list_select_related = ("deal_flag",)
    ordering = ("-pk",)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        custom_urls = [
            path(
                "untracked/",
                self.admin_site.admin_view(self.untracked_worklist_view),
                name="outcomes_outcome_untracked",
            ),
            path(
                "deal-flag/<int:deal_flag_id>/skip/",
                self.admin_site.admin_view(self.skip_view),
                name="outcomes_outcome_skip",
            ),
            path(
                "deal-flag/<int:deal_flag_id>/record-purchase/",
                self.admin_site.admin_view(self.record_purchase_view),
                name="outcomes_outcome_record_purchase",
            ),
            path(
                "deal-flag/<int:deal_flag_id>/record-sale/",
                self.admin_site.admin_view(self.record_sale_view),
                name="outcomes_outcome_record_sale",
            ),
            path(
                "deal-flag/<int:deal_flag_id>/correct-purchase/",
                self.admin_site.admin_view(self.correct_purchase_view),
                name="outcomes_outcome_correct_purchase",
            ),
            path(
                "deal-flag/<int:deal_flag_id>/correct-sale/",
                self.admin_site.admin_view(self.correct_sale_view),
                name="outcomes_outcome_correct_sale",
            ),
        ]
        return custom_urls + super().get_urls()

    def untracked_worklist_view(self, request):
        if not (
            request.user.has_perm("pricing.view_dealflag")
            and request.user.has_perm("outcomes.view_outcome")
        ):
            raise PermissionDenied

        deal_flags = DealFlag.objects.filter(outcome__isnull=True).order_by(
            "-flagged_at", "pk"
        )
        template = engines["django"].from_string(_UNTRACKED_TEMPLATE_SOURCE)
        context = {
            **self.admin_site.each_context(request),
            "title": "Deal flags without a recorded Outcome",
            "deal_flags": deal_flags,
        }
        return HttpResponse(template.render(context, request))

    def _audit_writer(self, request):
        # get_urls() views have no automatic secondary logging hook, unlike
        # ListingAdmin.save_model — so this is the only LogEntry write for
        # the request; no duplicate-suppression flag is needed. See TASK_028
        # specification Section 11.2.
        def write(outcome, change_message, action_flag):
            if action_flag == ADDITION:
                self.log_addition(request, outcome, change_message)
            else:
                self.log_change(request, outcome, change_message)

        return write

    @staticmethod
    def _redirect_to_changelist():
        return HttpResponseRedirect(reverse("admin:outcomes_outcome_changelist"))

    def _run_operation(self, request, service_call, success_message):
        try:
            service_call()
        except outcome_services.OutcomePermissionDenied as error:
            raise PermissionDenied from error
        except outcome_services.OutcomeNotFound as error:
            raise Http404(error.detail) from error
        except (
            outcome_services.OutcomeConflict,
            outcome_services.OutcomeValidationError,
        ) as error:
            self.message_user(request, error.detail, level=messages.WARNING)
            return self._redirect_to_changelist()

        self.message_user(request, success_message)
        return self._redirect_to_changelist()

    def skip_view(self, request, deal_flag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        skip_reason = request.POST.get("skip_reason", "")
        return self._run_operation(
            request,
            lambda: outcome_services.skip(
                actor=request.user,
                deal_flag_id=deal_flag_id,
                skip_reason=skip_reason,
                audit_writer=self._audit_writer(request),
            ),
            "Deal flag marked skipped.",
        )

    def record_purchase_view(self, request, deal_flag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        bought_at = _parse_admin_datetime(request.POST.get("bought_at"))
        bought_price = _parse_admin_decimal(request.POST.get("bought_price"))
        return self._run_operation(
            request,
            lambda: outcome_services.record_purchase(
                actor=request.user,
                deal_flag_id=deal_flag_id,
                bought_at=bought_at,
                bought_price=bought_price,
                audit_writer=self._audit_writer(request),
            ),
            "Purchase recorded.",
        )

    def record_sale_view(self, request, deal_flag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        sold_at = _parse_admin_datetime(request.POST.get("sold_at"))
        sold_price = _parse_admin_decimal(request.POST.get("sold_price"))
        return self._run_operation(
            request,
            lambda: outcome_services.record_sale(
                actor=request.user,
                deal_flag_id=deal_flag_id,
                sold_at=sold_at,
                sold_price=sold_price,
                audit_writer=self._audit_writer(request),
            ),
            "Sale recorded.",
        )

    def correct_purchase_view(self, request, deal_flag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        bought_at = _parse_admin_datetime(request.POST.get("bought_at"))
        bought_price = _parse_admin_decimal(request.POST.get("bought_price"))
        return self._run_operation(
            request,
            lambda: outcome_services.correct_purchase(
                actor=request.user,
                deal_flag_id=deal_flag_id,
                bought_at=bought_at,
                bought_price=bought_price,
                audit_writer=self._audit_writer(request),
            ),
            "Purchase evidence corrected.",
        )

    def correct_sale_view(self, request, deal_flag_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])

        sold_at = _parse_admin_datetime(request.POST.get("sold_at"))
        sold_price = _parse_admin_decimal(request.POST.get("sold_price"))
        return self._run_operation(
            request,
            lambda: outcome_services.correct_sale(
                actor=request.user,
                deal_flag_id=deal_flag_id,
                sold_at=sold_at,
                sold_price=sold_price,
                audit_writer=self._audit_writer(request),
            ),
            "Sale evidence corrected.",
        )
