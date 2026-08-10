from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Callable

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import DecimalValidator
from django.db import IntegrityError, transaction

from outcomes.models import Outcome
from pricing.bucketing import manila_day
from pricing.models import DealFlag


PERMISSION_DENIED_DETAIL = "Active staff status and required permissions are required."
DEAL_FLAG_NOT_FOUND_DETAIL = "Deal flag not found."
OUTCOME_NOT_FOUND_DETAIL = "Outcome not found."
OUTCOME_ALREADY_EXISTS_DETAIL = "An outcome already exists for this deal flag."
INELIGIBLE_OUTCOME_STATE_DETAIL = "Outcome is not in an eligible state for this operation."
INVALID_OUTCOME_STATE_DETAIL = (
    "Outcome is in an invalid persisted state and must be corrected manually."
)
PRICE_INVALID_DETAIL = (
    "Price must be a finite, non-negative Decimal within the field's precision."
)
TIMESTAMP_INVALID_DETAIL = "Timestamp must be a timezone-aware datetime."
SKIP_REASON_INVALID_DETAIL = "skip_reason must be a non-empty string."
SALE_BEFORE_PURCHASE_DETAIL = "sold_at must not be earlier than bought_at."

# Exact and frozen — see TASK_028 specification Section 15.
SKIP_MESSAGE = "Skipped deal flag."
PURCHASE_MESSAGE = "Recorded purchase."
PURCHASE_AFTER_SKIP_MESSAGE = "Recorded purchase after previously skipping."
SALE_MESSAGE = "Recorded sale."
CORRECT_PURCHASE_MESSAGE = "Corrected purchase evidence."
CORRECT_SALE_MESSAGE = "Corrected sale evidence."

_PRICE_VALIDATOR = DecimalValidator(max_digits=12, decimal_places=2)


@dataclass(frozen=True, slots=True)
class OutcomeState:
    deal_flag_id: int
    outcome_id: int | None
    lifecycle_state: str
    acted: bool | None
    skip_reason: str | None
    bought_at: datetime | None
    bought_price: Decimal | None
    sold_at: datetime | None
    sold_price: Decimal | None
    days_held: int | None
    realised_margin: Decimal | None


@dataclass(frozen=True, slots=True)
class OutcomeOperationResult:
    operation: str
    deal_flag_id: int
    outcome_id: int | None
    lifecycle_state: str
    acted: bool | None
    skip_reason: str | None
    bought_at: datetime | None
    bought_price: Decimal | None
    sold_at: datetime | None
    sold_price: Decimal | None
    days_held: int | None
    realised_margin: Decimal | None


class _OutcomeServiceError(Exception):
    def __init__(self, *, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


class OutcomePermissionDenied(_OutcomeServiceError):
    pass


class OutcomeNotFound(_OutcomeServiceError):
    pass


class OutcomeConflict(_OutcomeServiceError):
    pass


class OutcomeValidationError(_OutcomeServiceError):
    pass


AuditWriter = Callable[[Outcome, str, int], None]


def _require_permissions(*, actor, extra_perm: str) -> None:
    # A service call must observe grants or revocations made after an earlier decision.
    for cache_name in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        if hasattr(actor, cache_name):
            delattr(actor, cache_name)

    permitted = (
        getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_staff", False)
        and actor.has_perm("pricing.view_dealflag")
        and actor.has_perm(extra_perm)
    )
    if not permitted:
        raise OutcomePermissionDenied(
            code="permission_denied",
            detail=PERMISSION_DENIED_DETAIL,
        )


def _fetch_deal_flag(*, deal_flag_id: int) -> DealFlag:
    try:
        return DealFlag.objects.get(pk=deal_flag_id)
    except DealFlag.DoesNotExist as error:
        raise OutcomeNotFound(
            code="deal_flag_not_found",
            detail=DEAL_FLAG_NOT_FOUND_DETAIL,
        ) from error


def _locked_outcome_or_none(*, deal_flag: DealFlag) -> Outcome | None:
    return Outcome.objects.select_for_update().filter(deal_flag=deal_flag).first()


def _classify_or_raise(outcome: Outcome) -> str:
    """Return 'skipped' | 'open' | 'closed' for a persisted row, or raise
    OutcomeConflict(invalid_outcome_state) if the row matches none of the
    four approved lifecycle states. See TASK_028 specification Section 5.1.
    """
    has_bought = outcome.bought_at is not None and outcome.bought_price is not None
    partial_bought = (outcome.bought_at is not None) != (outcome.bought_price is not None)
    has_sold = outcome.sold_at is not None and outcome.sold_price is not None
    partial_sold = (outcome.sold_at is not None) != (outcome.sold_price is not None)

    if partial_bought or partial_sold:
        raise OutcomeConflict(code="invalid_outcome_state", detail=INVALID_OUTCOME_STATE_DETAIL)

    if not outcome.acted:
        has_valid_reason = bool(outcome.skip_reason) and outcome.skip_reason.strip() != ""
        if has_valid_reason and not has_bought and not has_sold:
            return "skipped"
        raise OutcomeConflict(code="invalid_outcome_state", detail=INVALID_OUTCOME_STATE_DETAIL)

    if not has_bought:
        raise OutcomeConflict(code="invalid_outcome_state", detail=INVALID_OUTCOME_STATE_DETAIL)
    return "closed" if has_sold else "open"


def _validate_skip_reason(value) -> str:
    if not isinstance(value, str):
        raise OutcomeValidationError(code="invalid_request", detail=SKIP_REASON_INVALID_DETAIL)
    stripped = value.strip()
    if not stripped:
        raise OutcomeValidationError(code="invalid_request", detail=SKIP_REASON_INVALID_DETAIL)
    return stripped


def _validate_price(value) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise OutcomeValidationError(code="invalid_request", detail=PRICE_INVALID_DETAIL)
    if value < 0:
        raise OutcomeValidationError(code="invalid_request", detail=PRICE_INVALID_DETAIL)
    try:
        _PRICE_VALIDATOR(value)
    except DjangoValidationError as error:
        raise OutcomeValidationError(
            code="invalid_request", detail=PRICE_INVALID_DETAIL
        ) from error
    return value


def _validate_timestamp(value) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise OutcomeValidationError(code="invalid_request", detail=TIMESTAMP_INVALID_DETAIL)
    return value


def _validate_ordering(*, bought_at: datetime, sold_at: datetime) -> None:
    if sold_at < bought_at:
        raise OutcomeValidationError(
            code="invalid_request", detail=SALE_BEFORE_PURCHASE_DETAIL
        )


def _compute_days_held(*, bought_at: datetime, sold_at: datetime) -> int:
    return (manila_day(sold_at) - manila_day(bought_at)).days


def _create_outcome(
    *,
    deal_flag: DealFlag,
    acted: bool,
    skip_reason: str | None,
    bought_at: datetime | None,
    bought_price: Decimal | None,
) -> Outcome:
    try:
        # The savepoint keeps a uniqueness race from breaking the outer decision.
        with transaction.atomic():
            return Outcome.objects.create(
                deal_flag=deal_flag,
                acted=acted,
                skip_reason=skip_reason,
                bought_at=bought_at,
                bought_price=bought_price,
                sold_at=None,
                sold_price=None,
                days_held=None,
            )
    except IntegrityError as error:
        raise OutcomeConflict(
            code="outcome_already_exists",
            detail=OUTCOME_ALREADY_EXISTS_DETAIL,
        ) from error


def _write_audit(
    *,
    actor,
    outcome: Outcome,
    change_message: str,
    action_flag: int,
    audit_writer: AuditWriter | None,
) -> None:
    if audit_writer is not None:
        audit_writer(outcome, change_message, action_flag)
        return

    LogEntry.objects.create(
        user_id=actor.pk,
        content_type=ContentType.objects.get_for_model(Outcome),
        object_id=str(outcome.pk),
        object_repr=str(outcome),
        action_flag=action_flag,
        change_message=change_message,
    )


def _state_fields(*, deal_flag_id: int, outcome: Outcome | None, lifecycle_state: str) -> dict:
    if outcome is None:
        return dict(
            deal_flag_id=deal_flag_id,
            outcome_id=None,
            lifecycle_state=lifecycle_state,
            acted=None,
            skip_reason=None,
            bought_at=None,
            bought_price=None,
            sold_at=None,
            sold_price=None,
            days_held=None,
            realised_margin=None,
        )
    return dict(
        deal_flag_id=deal_flag_id,
        outcome_id=outcome.pk,
        lifecycle_state=lifecycle_state,
        acted=outcome.acted,
        skip_reason=outcome.skip_reason,
        bought_at=outcome.bought_at,
        bought_price=outcome.bought_price,
        sold_at=outcome.sold_at,
        sold_price=outcome.sold_price,
        days_held=outcome.days_held,
        realised_margin=outcome.realised_margin,
    )


def get_outcome_state(*, actor, deal_flag_id: int) -> OutcomeState:
    _require_permissions(actor=actor, extra_perm="outcomes.view_outcome")

    deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
    outcome = Outcome.objects.filter(deal_flag=deal_flag).first()
    if outcome is None:
        return OutcomeState(
            **_state_fields(deal_flag_id=deal_flag.pk, outcome=None, lifecycle_state="untracked")
        )

    lifecycle_state = _classify_or_raise(outcome)
    return OutcomeState(
        **_state_fields(deal_flag_id=deal_flag.pk, outcome=outcome, lifecycle_state=lifecycle_state)
    )


def skip(
    *, actor, deal_flag_id: int, skip_reason: str, audit_writer: AuditWriter | None = None
) -> OutcomeOperationResult:
    _require_permissions(actor=actor, extra_perm="outcomes.add_outcome")
    cleaned_reason = _validate_skip_reason(skip_reason)

    with transaction.atomic():
        deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
        existing = _locked_outcome_or_none(deal_flag=deal_flag)

        if existing is not None:
            # Invalid persisted state is reported before any transition logic runs.
            _classify_or_raise(existing)
            raise OutcomeConflict(
                code="outcome_already_exists",
                detail=OUTCOME_ALREADY_EXISTS_DETAIL,
            )

        outcome = _create_outcome(
            deal_flag=deal_flag,
            acted=False,
            skip_reason=cleaned_reason,
            bought_at=None,
            bought_price=None,
        )
        outcome.refresh_from_db()

        _write_audit(
            actor=actor,
            outcome=outcome,
            change_message=SKIP_MESSAGE,
            action_flag=ADDITION,
            audit_writer=audit_writer,
        )

        return OutcomeOperationResult(
            operation="skip",
            **_state_fields(deal_flag_id=deal_flag.pk, outcome=outcome, lifecycle_state="skipped"),
        )


def record_purchase(
    *,
    actor,
    deal_flag_id: int,
    bought_at,
    bought_price,
    audit_writer: AuditWriter | None = None,
) -> OutcomeOperationResult:
    _require_permissions(actor=actor, extra_perm="outcomes.add_outcome")
    cleaned_bought_at = _validate_timestamp(bought_at)
    cleaned_bought_price = _validate_price(bought_price)

    with transaction.atomic():
        deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
        existing = _locked_outcome_or_none(deal_flag=deal_flag)

        if existing is None:
            outcome = _create_outcome(
                deal_flag=deal_flag,
                acted=True,
                skip_reason=None,
                bought_at=cleaned_bought_at,
                bought_price=cleaned_bought_price,
            )
            outcome.refresh_from_db()
            action_flag = ADDITION
            change_message = PURCHASE_MESSAGE
        else:
            lifecycle_state = _classify_or_raise(existing)
            if lifecycle_state != "skipped":
                raise OutcomeConflict(
                    code="outcome_already_exists",
                    detail=OUTCOME_ALREADY_EXISTS_DETAIL,
                )

            # An explicit, audited decision change — not repair of the prior skip.
            existing.acted = True
            existing.skip_reason = None
            existing.bought_at = cleaned_bought_at
            existing.bought_price = cleaned_bought_price
            existing.save(update_fields=["acted", "skip_reason", "bought_at", "bought_price"])
            existing.refresh_from_db()
            outcome = existing
            action_flag = CHANGE
            change_message = PURCHASE_AFTER_SKIP_MESSAGE

        _write_audit(
            actor=actor,
            outcome=outcome,
            change_message=change_message,
            action_flag=action_flag,
            audit_writer=audit_writer,
        )

        return OutcomeOperationResult(
            operation="record_purchase",
            **_state_fields(deal_flag_id=deal_flag.pk, outcome=outcome, lifecycle_state="open"),
        )


def record_sale(
    *,
    actor,
    deal_flag_id: int,
    sold_at,
    sold_price,
    audit_writer: AuditWriter | None = None,
) -> OutcomeOperationResult:
    _require_permissions(actor=actor, extra_perm="outcomes.change_outcome")
    cleaned_sold_at = _validate_timestamp(sold_at)
    cleaned_sold_price = _validate_price(sold_price)

    with transaction.atomic():
        deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
        existing = _locked_outcome_or_none(deal_flag=deal_flag)
        if existing is None:
            raise OutcomeNotFound(code="outcome_not_found", detail=OUTCOME_NOT_FOUND_DETAIL)

        lifecycle_state = _classify_or_raise(existing)
        if lifecycle_state != "open":
            raise OutcomeConflict(
                code="ineligible_outcome_state",
                detail=INELIGIBLE_OUTCOME_STATE_DETAIL,
            )

        _validate_ordering(bought_at=existing.bought_at, sold_at=cleaned_sold_at)

        existing.sold_at = cleaned_sold_at
        existing.sold_price = cleaned_sold_price
        existing.days_held = _compute_days_held(
            bought_at=existing.bought_at, sold_at=cleaned_sold_at
        )
        existing.save(update_fields=["sold_at", "sold_price", "days_held"])
        existing.refresh_from_db()

        _write_audit(
            actor=actor,
            outcome=existing,
            change_message=SALE_MESSAGE,
            action_flag=CHANGE,
            audit_writer=audit_writer,
        )

        return OutcomeOperationResult(
            operation="record_sale",
            **_state_fields(deal_flag_id=deal_flag.pk, outcome=existing, lifecycle_state="closed"),
        )


def correct_purchase(
    *,
    actor,
    deal_flag_id: int,
    bought_at,
    bought_price,
    audit_writer: AuditWriter | None = None,
) -> OutcomeOperationResult:
    _require_permissions(actor=actor, extra_perm="outcomes.change_outcome")
    cleaned_bought_at = _validate_timestamp(bought_at)
    cleaned_bought_price = _validate_price(bought_price)

    with transaction.atomic():
        deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
        existing = _locked_outcome_or_none(deal_flag=deal_flag)
        if existing is None:
            raise OutcomeNotFound(code="outcome_not_found", detail=OUTCOME_NOT_FOUND_DETAIL)

        lifecycle_state = _classify_or_raise(existing)
        if lifecycle_state not in ("open", "closed"):
            raise OutcomeConflict(
                code="ineligible_outcome_state",
                detail=INELIGIBLE_OUTCOME_STATE_DETAIL,
            )

        update_fields = ["bought_at", "bought_price"]
        if lifecycle_state == "closed":
            _validate_ordering(bought_at=cleaned_bought_at, sold_at=existing.sold_at)
            existing.days_held = _compute_days_held(
                bought_at=cleaned_bought_at, sold_at=existing.sold_at
            )
            update_fields.append("days_held")

        existing.bought_at = cleaned_bought_at
        existing.bought_price = cleaned_bought_price
        existing.save(update_fields=update_fields)
        existing.refresh_from_db()

        _write_audit(
            actor=actor,
            outcome=existing,
            change_message=CORRECT_PURCHASE_MESSAGE,
            action_flag=CHANGE,
            audit_writer=audit_writer,
        )

        return OutcomeOperationResult(
            operation="correct_purchase",
            **_state_fields(
                deal_flag_id=deal_flag.pk, outcome=existing, lifecycle_state=lifecycle_state
            ),
        )


def correct_sale(
    *,
    actor,
    deal_flag_id: int,
    sold_at,
    sold_price,
    audit_writer: AuditWriter | None = None,
) -> OutcomeOperationResult:
    _require_permissions(actor=actor, extra_perm="outcomes.change_outcome")
    cleaned_sold_at = _validate_timestamp(sold_at)
    cleaned_sold_price = _validate_price(sold_price)

    with transaction.atomic():
        deal_flag = _fetch_deal_flag(deal_flag_id=deal_flag_id)
        existing = _locked_outcome_or_none(deal_flag=deal_flag)
        if existing is None:
            raise OutcomeNotFound(code="outcome_not_found", detail=OUTCOME_NOT_FOUND_DETAIL)

        lifecycle_state = _classify_or_raise(existing)
        if lifecycle_state != "closed":
            raise OutcomeConflict(
                code="ineligible_outcome_state",
                detail=INELIGIBLE_OUTCOME_STATE_DETAIL,
            )

        _validate_ordering(bought_at=existing.bought_at, sold_at=cleaned_sold_at)

        existing.sold_at = cleaned_sold_at
        existing.sold_price = cleaned_sold_price
        existing.days_held = _compute_days_held(
            bought_at=existing.bought_at, sold_at=cleaned_sold_at
        )
        existing.save(update_fields=["sold_at", "sold_price", "days_held"])
        existing.refresh_from_db()

        _write_audit(
            actor=actor,
            outcome=existing,
            change_message=CORRECT_SALE_MESSAGE,
            action_flag=CHANGE,
            audit_writer=audit_writer,
        )

        return OutcomeOperationResult(
            operation="correct_sale",
            **_state_fields(deal_flag_id=deal_flag.pk, outcome=existing, lifecycle_state="closed"),
        )
