from django.db import migrations, models
from django.db.models import Count, F, Q


CREATE_IMMUTABILITY_TRIGGERS_SQL = """
CREATE OR REPLACE FUNCTION pricing_pricepoint_task019_block_update_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'PricePoint is immutable: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pricing_pricepoint_task019_immutable
BEFORE UPDATE OR DELETE ON pricing_pricepoint
FOR EACH ROW EXECUTE FUNCTION pricing_pricepoint_task019_block_update_delete();

CREATE OR REPLACE FUNCTION pricing_dealflag_task019_block_update_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'DealFlag is immutable: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER pricing_dealflag_task019_immutable
BEFORE UPDATE OR DELETE ON pricing_dealflag
FOR EACH ROW EXECUTE FUNCTION pricing_dealflag_task019_block_update_delete();
"""

DROP_IMMUTABILITY_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS pricing_dealflag_task019_immutable ON pricing_dealflag;
DROP FUNCTION IF EXISTS pricing_dealflag_task019_block_update_delete();
DROP TRIGGER IF EXISTS pricing_pricepoint_task019_immutable ON pricing_pricepoint;
DROP FUNCTION IF EXISTS pricing_pricepoint_task019_block_update_delete();
"""


def require_one_dealflag_per_listing(apps, schema_editor):
    DealFlag = apps.get_model("pricing", "DealFlag")
    database_alias = schema_editor.connection.alias
    # Duplicate historical evidence needs an owner decision, so this only identifies it.
    duplicate = (
        DealFlag.objects.using(database_alias)
        .values("listing_id")
        .annotate(flag_count=Count("id"))
        .filter(flag_count__gt=1)
        .order_by("listing_id")
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            "Cannot add dealflag_listing_unique: "
            f"listing_id={duplicate['listing_id']} has "
            f"{duplicate['flag_count']} DealFlag rows. "
            "Duplicate pricing evidence must be resolved by the owner."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="pricepoint",
            name="median",
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
        migrations.AlterField(
            model_name="pricepoint",
            name="p25",
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
        migrations.AlterField(
            model_name="pricepoint",
            name="p75",
            field=models.DecimalField(decimal_places=4, max_digits=14),
        ),
        migrations.AddField(
            model_name="pricepoint",
            name="mad",
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                max_digits=14,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="pricepoint",
            name="window_start_day",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pricepoint",
            name="window_end_day",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pricepoint",
            name="calculated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="pricepoint",
            name="calculation_contract_version",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddConstraint(
            model_name="pricepoint",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        mad__isnull=True,
                        window_start_day__isnull=True,
                        window_end_day__isnull=True,
                        calculated_at__isnull=True,
                        calculation_contract_version__isnull=True,
                    )
                    | Q(
                        mad__isnull=False,
                        window_start_day__isnull=False,
                        window_end_day__isnull=False,
                        calculated_at__isnull=False,
                        calculation_contract_version__isnull=False,
                    )
                ),
                name="pricepoint_audit_metadata_complete",
            ),
        ),
        migrations.AddConstraint(
            model_name="pricepoint",
            constraint=models.CheckConstraint(
                condition=Q(mad__isnull=True) | Q(mad__gte=0),
                name="pricepoint_mad_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="pricepoint",
            constraint=models.CheckConstraint(
                condition=(
                    Q(calculation_contract_version__isnull=True)
                    | ~Q(calculation_contract_version="")
                ),
                name="pricepoint_contract_version_non_blank",
            ),
        ),
        migrations.AddConstraint(
            model_name="pricepoint",
            constraint=models.CheckConstraint(
                condition=(
                    Q(window_start_day__isnull=True)
                    | Q(window_start_day__lt=F("window_end_day"))
                ),
                name="pricepoint_window_bounds_ordered",
            ),
        ),
        migrations.AlterField(
            model_name="dealflag",
            name="score",
            field=models.DecimalField(decimal_places=4, max_digits=18),
        ),
        migrations.RunPython(
            require_one_dealflag_per_listing,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="dealflag",
            constraint=models.UniqueConstraint(
                fields=("listing",),
                name="dealflag_listing_unique",
            ),
        ),
        migrations.RunSQL(
            CREATE_IMMUTABILITY_TRIGGERS_SQL,
            reverse_sql=DROP_IMMUTABILITY_TRIGGERS_SQL,
        ),
    ]
