import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from catalogue.models import Sku
from listings.models import Listing
from pricing.baselines import build_pricepoint
from pricing.scoring import score_listing


_ISO_DAY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def _current_manila_day() -> date:
    aggregation_timezone = ZoneInfo(settings.AGGREGATION_TIME_ZONE)
    return timezone.now().astimezone(aggregation_timezone).date()


def _parse_explicit_day(value: str) -> date:
    if not _ISO_DAY_PATTERN.fullmatch(value):
        raise CommandError("--day must be a valid date in YYYY-MM-DD form.")

    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise CommandError(
            "--day must be a valid date in YYYY-MM-DD form."
        ) from error


def _manila_day_bounds(run_day: date) -> tuple[datetime, datetime]:
    aggregation_timezone = ZoneInfo(settings.AGGREGATION_TIME_ZONE)
    start = datetime.combine(run_day, time.min, tzinfo=aggregation_timezone)
    end = datetime.combine(
        run_day + timedelta(days=1),
        time.min,
        tzinfo=aggregation_timezone,
    )
    return start, end


class Command(BaseCommand):
    help = "Build current pricing evidence and score Listings for one Manila day."

    def add_arguments(self, parser):
        parser.add_argument("--day", metavar="YYYY-MM-DD")

    def handle(self, *args, **options):
        current_day = _current_manila_day()
        run_day = (
            current_day
            if options["day"] is None
            else _parse_explicit_day(options["day"])
        )
        if run_day > current_day:
            raise CommandError("Cannot price a future Manila day.")

        day_start, next_day_start = _manila_day_bounds(run_day)
        snapshot_identities = 0
        listings_evaluated = 0

        with transaction.atomic():
            if run_day == current_day:
                identities = list(
                    Listing.objects.filter(
                        observed_at__gte=day_start,
                        observed_at__lt=next_day_start,
                        sku_id__isnull=False,
                        condition__isnull=False,
                    )
                    .order_by("sku_id", "condition")
                    .values_list("sku_id", "condition")
                    .distinct()
                )
                for sku_id, condition in identities:
                    sku = Sku.objects.get(pk=sku_id)
                    build_pricepoint(
                        sku=sku,
                        condition=condition,
                        as_of_day=run_day,
                    )
                snapshot_identities = len(identities)

            # DISTINCT makes the two event arms one stable operational worklist.
            scoring_candidates = list(
                Listing.objects.filter(
                    Q(
                        observed_at__gte=day_start,
                        observed_at__lt=next_day_start,
                    )
                    | Q(
                        resolved_at__gte=day_start,
                        resolved_at__lt=next_day_start,
                    )
                )
                .order_by("pk")
                .distinct()
            )
            for listing in scoring_candidates:
                score_listing(listing=listing)
            listings_evaluated = len(scoring_candidates)

        self.stdout.write(
            f"Pricing {run_day.isoformat()} complete: "
            f"snapshot_identities={snapshot_identities} "
            f"listings_evaluated={listings_evaluated}"
        )
