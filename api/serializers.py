from collections.abc import Mapping
from datetime import timezone as datetime_timezone

from rest_framework import serializers

from catalogue.models import Sku
from listings.models import Listing
from pricing.models import DealFlag, PricePoint


class UTCDateTimeField(serializers.DateTimeField):
    # API instants stay in UTC even if Django's active display timezone changes.
    def __init__(self, **kwargs):
        kwargs["default_timezone"] = datetime_timezone.utc
        super().__init__(**kwargs)


class StrictRequestSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            raise serializers.ValidationError(
                {"non_field_errors": ["Expected a JSON object."]}
            )

        unknown_fields = sorted(set(data) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {field: ["Unknown field."] for field in unknown_fields}
            )
        return super().to_internal_value(data)


class StrictPositiveIntegerField(serializers.IntegerField):
    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    def to_internal_value(self, data):
        if type(data) is not bool:
            self.fail("invalid", input=data)
        return data


class MarkReviewedUnresolvedRequestSerializer(StrictRequestSerializer):
    pass


class ConfirmSkuRequestSerializer(StrictRequestSerializer):
    sku_id = StrictPositiveIntegerField(min_value=1)
    create_alias = StrictBooleanField(required=False, default=False)


class MarkReviewedUnresolvedResponseSerializer(serializers.Serializer):
    operation = serializers.CharField(read_only=True)
    listing_id = serializers.IntegerField(read_only=True)
    reviewed_unresolved_at = UTCDateTimeField(read_only=True)


class ConfirmSkuResponseSerializer(serializers.Serializer):
    operation = serializers.CharField(read_only=True)
    listing_id = serializers.IntegerField(read_only=True)
    sku_id = serializers.IntegerField(read_only=True)
    resolution_method = serializers.CharField(read_only=True)
    resolution_confidence = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    resolved_at = UTCDateTimeField(read_only=True)
    reviewed_unresolved_at = UTCDateTimeField(allow_null=True, read_only=True)
    alias_status = serializers.CharField(read_only=True)


class SkuSerializer(serializers.ModelSerializer):
    launch_msrp = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        coerce_to_string=True,
        read_only=True,
    )
    launch_date = serializers.DateField(read_only=True)

    class Meta:
        model = Sku
        fields = (
            "id",
            "brand",
            "model",
            "variant",
            "category",
            "launch_msrp",
            "launch_date",
        )
        read_only_fields = fields


class SkuSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Sku
        fields = (
            "id",
            "brand",
            "model",
            "variant",
            "category",
        )
        read_only_fields = fields


class ListingSerializer(serializers.ModelSerializer):
    sku_id = serializers.IntegerField(allow_null=True, read_only=True)
    price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        allow_null=True,
        coerce_to_string=True,
        read_only=True,
    )
    resolution_confidence = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    resolved_at = UTCDateTimeField(read_only=True)
    observed_at = UTCDateTimeField(allow_null=True, read_only=True)

    class Meta:
        model = Listing
        fields = (
            "id",
            "sku_id",
            "price",
            "condition",
            "resolution_confidence",
            "resolution_method",
            "resolved_at",
            "observed_at",
            "price_kind",
            "trade_side",
        )
        read_only_fields = fields


class PricePointSerializer(serializers.ModelSerializer):
    sku_id = serializers.IntegerField(read_only=True)
    day = serializers.DateField(read_only=True)
    median = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    p25 = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    p75 = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    mad = serializers.DecimalField(
        max_digits=14,
        decimal_places=4,
        allow_null=True,
        coerce_to_string=True,
        read_only=True,
    )
    window_start_day = serializers.DateField(allow_null=True, read_only=True)
    window_end_day = serializers.DateField(allow_null=True, read_only=True)
    calculated_at = UTCDateTimeField(allow_null=True, read_only=True)

    class Meta:
        model = PricePoint
        fields = (
            "id",
            "sku_id",
            "condition",
            "day",
            "median",
            "p25",
            "p75",
            "n_listings",
            "mad",
            "window_start_day",
            "window_end_day",
            "calculated_at",
            "calculation_contract_version",
        )
        read_only_fields = fields


class DealFlagSerializer(serializers.ModelSerializer):
    sku = SkuSummarySerializer(source="baseline_pricepoint.sku", read_only=True)
    listing = ListingSerializer(read_only=True)
    baseline_pricepoint = PricePointSerializer(read_only=True)
    score = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        coerce_to_string=True,
        read_only=True,
    )
    flagged_at = UTCDateTimeField(read_only=True)

    class Meta:
        model = DealFlag
        fields = (
            "id",
            "sku",
            "listing",
            "baseline_pricepoint",
            "score",
            "reason",
            "flagged_at",
        )
        read_only_fields = fields
