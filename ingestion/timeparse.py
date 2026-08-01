from datetime import date, datetime, time, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings


def manila_midnight(day: date) -> datetime:
    """Interpret a bare source date as midnight in AGGREGATION_TIME_ZONE.

    UTC midnight also happens to round-trip correctly for Manila, but only by
    luck of the offset's sign. Reading the date in the zone the source
    actually meant is correct by construction. See TASK_005 Decision 4.
    """
    local_midnight = datetime.combine(day, time.min, tzinfo=ZoneInfo(settings.AGGREGATION_TIME_ZONE))
    return local_midnight.astimezone(dt_timezone.utc)
