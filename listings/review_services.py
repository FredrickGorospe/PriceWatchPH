from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogue.models import Sku, SkuAlias
from listings.models import Listing
from listings.normalisation import normalise_title


PERMISSION_DENIED_DETAIL = "Active staff status and required permissions are required."
LISTING_NOT_FOUND_DETAIL = "Listing not found."
SKU_NOT_FOUND_DETAIL = "SKU not found."
INELIGIBLE_REVIEW_DETAIL = (
    "Listing is not eligible to be marked reviewed unresolved."
)
ALIAS_CONFLICT_DETAIL = (
    "The normalized title is already an alias for a different SKU."
)


@dataclass(frozen=True, slots=True)
class ReviewOperationResult:
    operation: str
    listing_id: int
    sku_id: int | None
    resolution_method: str
    resolution_confidence: Decimal
    resolved_at: datetime
    reviewed_unresolved_at: datetime | None
    alias_status: str
    alias_id: int | None


class _ReviewServiceError(Exception):
    def __init__(self, *, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class ReviewPermissionDenied(_ReviewServiceError):
    pass


class ReviewNotFound(_ReviewServiceError):
    pass


class ReviewConflict(_ReviewServiceError):
    pass


AuditWriter = Callable[[Listing, str], None]


def _require_permissions(*, actor, create_alias: bool = False) -> None:
    # A service call must observe grants or revocations made after an earlier decision.
    for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(actor, cache_name):
            delattr(actor, cache_name)

    permitted = (
        getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_staff", False)
        and actor.has_perm("listings.change_listing")
    )
    if create_alias:
        permitted = permitted and actor.has_perm("catalogue.add_skualias")
    if not permitted:
        raise ReviewPermissionDenied(
            code="permission_denied",
            detail=PERMISSION_DENIED_DETAIL,
        )


def _locked_listing(*, listing_id: int, with_raw_listing: bool = False) -> Listing:
    queryset = Listing.objects.select_for_update(of=("self",))
    if with_raw_listing:
        queryset = queryset.select_related("raw_listing")
    try:
        return queryset.get(pk=listing_id)
    except Listing.DoesNotExist as error:
        raise ReviewNotFound(
            code="listing_not_found",
            detail=LISTING_NOT_FOUND_DETAIL,
        ) from error


def _selected_sku(*, sku_id: int) -> Sku:
    try:
        return Sku.objects.get(pk=sku_id)
    except Sku.DoesNotExist as error:
        raise ReviewNotFound(
            code="sku_not_found",
            detail=SKU_NOT_FOUND_DETAIL,
        ) from error


def _write_audit(
    *,
    actor,
    listing: Listing,
    change_message: str,
    audit_writer: AuditWriter | None,
) -> None:
    if audit_writer is not None:
        audit_writer(listing, change_message)
        return

    LogEntry.objects.create(
        user_id=actor.pk,
        content_type=ContentType.objects.get_for_model(Listing),
        object_id=str(listing.pk),
        object_repr=str(listing),
        action_flag=CHANGE,
        change_message=change_message,
    )


def _create_or_reuse_alias(
    *, listing: Listing, selected_sku: Sku
) -> tuple[str, int]:
    raw_title = listing.raw_listing.raw_title
    normalised_text = normalise_title(raw_title)
    existing_alias = SkuAlias.objects.filter(
        normalised_text=normalised_text,
    ).first()

    if existing_alias is None:
        try:
            # The savepoint keeps a uniqueness race from breaking the outer decision.
            with transaction.atomic():
                created_alias = SkuAlias.objects.create(
                    sku=selected_sku,
                    alias_text=raw_title,
                    normalised_text=normalised_text,
                    source_of_truth="human_confirmed",
                )
        except IntegrityError:
            existing_alias = SkuAlias.objects.filter(
                normalised_text=normalised_text,
            ).first()
            if existing_alias is None:
                raise
        else:
            return "created", created_alias.pk

    if existing_alias.sku_id != selected_sku.pk:
        raise ReviewConflict(
            code="alias_conflict",
            detail=ALIAS_CONFLICT_DETAIL,
        )
    return "already_exists", existing_alias.pk


def mark_reviewed_unresolved(
    *, actor, listing_id: int, audit_writer: AuditWriter | None = None
) -> ReviewOperationResult:
    _require_permissions(actor=actor)

    with transaction.atomic():
        listing = _locked_listing(listing_id=listing_id)
        if not (
            listing.sku_id is None
            and listing.resolution_method in {"unresolved", "fuzzy_match"}
        ):
            raise ReviewConflict(
                code="ineligible_review_state",
                detail=INELIGIBLE_REVIEW_DETAIL,
            )

        listing.reviewed_unresolved_at = timezone.now()
        listing.save(update_fields=["reviewed_unresolved_at"])
        _write_audit(
            actor=actor,
            listing=listing,
            change_message="Marked reviewed unresolved.",
            audit_writer=audit_writer,
        )

        return ReviewOperationResult(
            operation="mark_reviewed_unresolved",
            listing_id=listing.pk,
            sku_id=listing.sku_id,
            resolution_method=listing.resolution_method,
            resolution_confidence=listing.resolution_confidence,
            resolved_at=listing.resolved_at,
            reviewed_unresolved_at=listing.reviewed_unresolved_at,
            alias_status="not_requested",
            alias_id=None,
        )


def confirm_listing_sku(
    *,
    actor,
    listing_id: int,
    sku_id: int,
    create_alias: bool = False,
    audit_writer: AuditWriter | None = None,
) -> ReviewOperationResult:
    _require_permissions(actor=actor, create_alias=create_alias)

    with transaction.atomic():
        listing = _locked_listing(
            listing_id=listing_id,
            with_raw_listing=create_alias,
        )
        selected_sku = _selected_sku(sku_id=sku_id)

        listing.sku = selected_sku
        listing.resolution_method = "human_confirmed"
        listing.resolution_confidence = Decimal("1.0000")
        listing.resolved_at = timezone.now()
        listing.reviewed_unresolved_at = None
        listing.save(
            update_fields=[
                "sku",
                "resolution_method",
                "resolution_confidence",
                "resolved_at",
                "reviewed_unresolved_at",
            ]
        )

        alias_status = "not_requested"
        alias_id = None
        if create_alias:
            alias_status, alias_id = _create_or_reuse_alias(
                listing=listing,
                selected_sku=selected_sku,
            )

        _write_audit(
            actor=actor,
            listing=listing,
            change_message="Confirmed or corrected SKU.",
            audit_writer=audit_writer,
        )

        return ReviewOperationResult(
            operation="confirm_sku",
            listing_id=listing.pk,
            sku_id=listing.sku_id,
            resolution_method=listing.resolution_method,
            resolution_confidence=listing.resolution_confidence,
            resolved_at=listing.resolved_at,
            reviewed_unresolved_at=listing.reviewed_unresolved_at,
            alias_status=alias_status,
            alias_id=alias_id,
        )
