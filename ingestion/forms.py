from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from listings.models import CONDITION_CHOICES


TRADE_TYPE_CHOICES = [
    ("buy", "Buy"),
    ("sell", "Sell"),
    ("swap", "Swap"),
]

OPTIONAL_CONDITION_CHOICES = [("", "---------"), *CONDITION_CHOICES]


class LogPersonalTradeForm(forms.Form):
    trade_type = forms.ChoiceField(choices=TRADE_TYPE_CHOICES)
    occurred_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    counterparty = forms.CharField(required=False)

    item = forms.CharField(required=False)
    condition = forms.ChoiceField(
        choices=OPTIONAL_CONDITION_CHOICES,
        required=False,
    )
    price = forms.CharField(required=False)

    given_item = forms.CharField(required=False)
    given_condition = forms.ChoiceField(
        choices=OPTIONAL_CONDITION_CHOICES,
        required=False,
    )
    given_value = forms.CharField(required=False)
    received_item = forms.CharField(required=False)
    received_condition = forms.ChoiceField(
        choices=OPTIONAL_CONDITION_CHOICES,
        required=False,
    )
    received_value = forms.CharField(required=False)
    cash_adjustment = forms.CharField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        trade_type = cleaned_data.get("trade_type")

        if trade_type in {"buy", "sell"}:
            self._require_text("item")
            self._clean_money("price", required=True, non_negative=True)
        elif trade_type == "swap":
            self._require_text("given_item")
            self._require_text("received_item")
            self._clean_money("given_value", required=True, non_negative=True)
            self._clean_money("received_value", required=True, non_negative=True)
            self._clean_money("cash_adjustment", required=False, non_negative=False)

        return cleaned_data

    def _require_text(self, field_name):
        if not self.cleaned_data.get(field_name):
            self.add_error(field_name, "This field is required.")

    def _clean_money(self, field_name, *, required, non_negative):
        raw_value = self.data.get(field_name, "")
        decimal_field = forms.DecimalField(
            required=required,
            max_digits=12,
            decimal_places=2,
            min_value=Decimal("0") if non_negative else None,
        )
        try:
            value = decimal_field.clean(raw_value)
        except ValidationError as error:
            self.add_error(field_name, error)
            return

        self.cleaned_data[field_name] = value
        if field_name != "cash_adjustment":
            self.cleaned_data[f"{field_name}_text"] = raw_value
