from django.core.management.base import BaseCommand
from django.db import transaction

from ingestion.models import RawListing
from listings.resolver import resolve_raw_listing


class Command(BaseCommand):
    help = "Resolve every RawListing into its current derived Listing."

    @transaction.atomic
    def handle(self, *args, **options):
        # Stable ordering makes every operational invocation reproducible.
        for raw_listing in RawListing.objects.order_by("pk"):
            resolve_raw_listing(raw_listing)
