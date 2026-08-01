from ingestion.models import RawListing


def observed_at_for(raw_listing: RawListing):
    """The value the resolver writes to Listing.observed_at: the source's
    stated event date if it gave one, otherwise when this system fetched it.

    "The best available statement of when this price was true" is a weaker,
    different claim than "when the event happened" — see TASK_005 Decision 2.
    """
    return raw_listing.occurred_at or raw_listing.fetched_at
