import django.db.models.deletion
from django.db import migrations, models
from django.db.models import F, Q


# Purpose-built, not a blanket immutability trigger like TASK_019's: it must
# still permit exactly one transition (pending -> sent|failed) while blocking
# every other UPDATE, every INSERT that isn't pending, and every DELETE. See
# tasks/TASK_030_ALERT_DELIVERY_PERSISTENCE.md §7.2.
CREATE_LIFECYCLE_GUARD_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION alerts_alertdelivery_task030_enforce_lifecycle()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'AlertDelivery cannot be deleted: % is not permitted', TG_OP;
    ELSIF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending' THEN
            RAISE EXCEPTION 'AlertDelivery must be created pending, not: %', NEW.status;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.deal_flag_id IS DISTINCT FROM NEW.deal_flag_id THEN
            RAISE EXCEPTION 'AlertDelivery.deal_flag_id is immutable and cannot be reassigned';
        END IF;
        IF OLD.claimed_at IS DISTINCT FROM NEW.claimed_at THEN
            RAISE EXCEPTION 'AlertDelivery.claimed_at is immutable and cannot be rewritten';
        END IF;
        IF OLD.status <> 'pending' THEN
            RAISE EXCEPTION 'AlertDelivery.status is already terminal (%) and cannot transition again', OLD.status;
        END IF;
        IF NEW.status NOT IN ('sent', 'failed') THEN
            RAISE EXCEPTION 'AlertDelivery.status may only transition from pending to sent or failed, not: %', NEW.status;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER alerts_alertdelivery_task030_lifecycle_guard
BEFORE INSERT OR UPDATE OR DELETE ON alerts_alertdelivery
FOR EACH ROW EXECUTE FUNCTION alerts_alertdelivery_task030_enforce_lifecycle();
"""

DROP_LIFECYCLE_GUARD_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS alerts_alertdelivery_task030_lifecycle_guard ON alerts_alertdelivery;
DROP FUNCTION IF EXISTS alerts_alertdelivery_task030_enforce_lifecycle();
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("pricing", "0002_auditable_pricing_evidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
                        max_length=20,
                    ),
                ),
                ("claimed_at", models.DateTimeField()),
                ("terminal_at", models.DateTimeField(blank=True, null=True)),
                ("failure_detail", models.TextField(blank=True, null=True)),
                (
                    "deal_flag",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="alert_delivery",
                        to="pricing.dealflag",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="alertdelivery",
            constraint=models.CheckConstraint(
                condition=Q(status__in=["pending", "sent", "failed"]),
                name="alertdelivery_status_in_vocabulary",
            ),
        ),
        migrations.AddConstraint(
            model_name="alertdelivery",
            constraint=models.CheckConstraint(
                condition=(
                    (Q(status="pending") & Q(terminal_at__isnull=True))
                    | (Q(status__in=["sent", "failed"]) & Q(terminal_at__isnull=False))
                ),
                name="alertdelivery_terminal_at_matches_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="alertdelivery",
            constraint=models.CheckConstraint(
                condition=(
                    (Q(status="failed") & Q(failure_detail__isnull=False) & ~Q(failure_detail=""))
                    | (Q(status__in=["pending", "sent"]) & Q(failure_detail__isnull=True))
                ),
                name="alertdelivery_failure_detail_matches_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="alertdelivery",
            constraint=models.CheckConstraint(
                condition=Q(terminal_at__isnull=True) | Q(terminal_at__gte=F("claimed_at")),
                name="alertdelivery_terminal_at_not_before_claimed_at",
            ),
        ),
        migrations.RunSQL(
            CREATE_LIFECYCLE_GUARD_TRIGGER_SQL,
            reverse_sql=DROP_LIFECYCLE_GUARD_TRIGGER_SQL,
        ),
    ]
