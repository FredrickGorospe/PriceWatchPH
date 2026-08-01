from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings


def manila_day(instant: datetime):
    """The AGGREGATION_TIME_ZONE calendar date of an aware instant.

    This is what PricePoint.day buckets on (see the comment on that field) —
    never the UTC date, which splits a Manila evening across two buckets.
    See TASK_005 Decisions 2 and 3.
    """
    return instant.astimezone(ZoneInfo(settings.AGGREGATION_TIME_ZONE)).date()
