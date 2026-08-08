"""Synthetic catalogue fixtures only; these tests do not measure market accuracy."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.urls import reverse

# TASK_018 extends the frozen TASK_017 admin surface, so its stable synthetic
# factories and state helpers are reused rather than defining a divergent setup.
from listings.tests.test_task_017_constrained_review import (  # noqa: F401
    _audit_entries,
    _change_url,
    _grant,
    _listing_admin,
    _listing_state,
    _post_confirmation,
    _raw_state,
    listing_factory,
    raw_listing_factory,
    sku_factory,
    source,
    staff_user_factory,
)


def _alias_admin():
    from catalogue.models import SkuAlias

    return admin.site._registry[SkuAlias]


def _alias_state(alias):
    return (
        alias.sku_id,
        alias.alias_text,
        alias.normalised_text,
        alias.source_of_truth,
        alias.created_at,
    )


def _make_alias(sku, raw_title, *, alias_text=None, source_of_truth="seed"):
    from catalogue.models import SkuAlias
    from listings.normalisation import normalise_title

    return SkuAlias.objects.create(
        sku=sku,
        alias_text=alias_text if alias_text is not None else raw_title,
        normalised_text=normalise_title(raw_title),
        source_of_truth=source_of_truth,
    )


def _alias_delete_url(alias):
    return reverse("admin:catalogue_skualias_delete", args=[alias.pk])


def _sku_delete_url(sku):
    return reverse("admin:catalogue_sku_delete", args=[sku.pk])


def _bulk_delete(client, model_name, object_ids):
    return client.post(
        reverse(f"admin:catalogue_{model_name}_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [str(object_id) for object_id in object_ids],
            "post": "yes",
        },
    )


# --- explicit alias opt-in and fidelity ----------------------------------


def test_confirmation_without_alias_opt_in_creates_no_alias(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    listing = listing_factory()

    response = _post_confirmation(admin_client, listing, sku_factory())

    assert response.status_code == 302
    assert SkuAlias.objects.count() == 0


def test_confirmation_form_exposes_optional_unchecked_alias_opt_in(
    staff_user_factory,
    listing_factory,
):
    user = staff_user_factory(is_superuser=True)
    listing = listing_factory()
    from django.test import RequestFactory

    request = RequestFactory().get(_change_url(listing))
    request.user = user

    form_class = _listing_admin().get_form(request, obj=listing)

    assert tuple(form_class.base_fields) == ("sku", "create_alias")
    assert form_class.base_fields["sku"].required is True
    assert form_class.base_fields["create_alias"].required is False
    assert form_class.base_fields["create_alias"].initial is False


def test_alias_opt_in_creates_exact_human_confirmed_alias(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias
    from listings.normalisation import normalise_title

    raw = raw_listing_factory(raw_title="  ASUS RTX 4070—SUPER 12GB  ")
    listing = listing_factory(raw_listing=raw)
    selected_sku = sku_factory(model="RTX 4070 Super")

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )

    assert response.status_code == 302
    alias = SkuAlias.objects.get()
    assert alias.sku == selected_sku
    assert alias.alias_text == raw.raw_title
    assert alias.normalised_text == normalise_title(raw.raw_title)
    assert alias.source_of_truth == "human_confirmed"


def test_forged_alias_fields_cannot_change_derived_alias_values(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias
    from listings.normalisation import normalise_title

    raw = raw_listing_factory(raw_title="Synthetic RX 7900 XTX")
    listing = listing_factory(raw_listing=raw)
    selected_sku = sku_factory(model="RX 7900 XTX")
    forged_target = sku_factory(model="Forged target")

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
        alias_text="FORGED ALIAS TEXT",
        normalised_text="forged-normalised-text",
        alias_sku=str(forged_target.pk),
        source_of_truth="seed",
    )

    assert response.status_code == 302
    alias = SkuAlias.objects.get()
    assert alias.sku == selected_sku
    assert alias.alias_text == raw.raw_title
    assert alias.normalised_text == normalise_title(raw.raw_title)
    assert alias.source_of_truth == "human_confirmed"


def test_alias_opt_in_creates_no_sku_and_preserves_raw_and_listing_facts(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku, SkuAlias

    raw = raw_listing_factory(raw_title="Preserve exact source title")
    listing = listing_factory(raw_listing=raw, condition="for_parts")
    selected_sku = sku_factory()
    raw_before = _raw_state(raw)
    listing_before = _listing_state(listing)
    sku_count = Sku.objects.count()

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )

    assert response.status_code == 302
    raw.refresh_from_db()
    listing.refresh_from_db()
    assert _raw_state(raw) == raw_before
    assert listing.condition == listing_before["condition"]
    assert listing.price == listing_before["price"]
    assert listing.observed_at == listing_before["observed_at"]
    assert listing.location == listing_before["location"]
    assert listing.price_kind == listing_before["price_kind"]
    assert listing.trade_side == listing_before["trade_side"]
    assert Sku.objects.count() == sku_count
    assert SkuAlias.objects.count() == 1


# --- duplicate, conflict, transaction, and permissions -------------------


def test_same_sku_existing_alias_request_is_idempotent_and_unchanged(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Same normalised title")
    selected_sku = sku_factory()
    alias = _make_alias(
        selected_sku,
        raw.raw_title,
        alias_text="Earlier curated spelling",
        source_of_truth="seed",
    )
    alias_before = _alias_state(alias)
    listing = listing_factory(raw_listing=raw)

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )

    assert response.status_code == 302
    listing.refresh_from_db()
    alias.refresh_from_db()
    assert listing.sku == selected_sku
    assert listing.resolution_method == "human_confirmed"
    assert SkuAlias.objects.count() == 1
    assert _alias_state(alias) == alias_before


def test_conflicting_alias_blocks_confirmation_without_repointing(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    raw = raw_listing_factory(raw_title="Global alias conflict")
    existing_target = sku_factory(model="Existing target")
    selected_sku = sku_factory(model="Requested target")
    alias = _make_alias(existing_target, raw.raw_title)
    alias_before = _alias_state(alias)
    listing = listing_factory(raw_listing=raw)
    listing_before = _listing_state(listing)

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )

    assert response.status_code == 200
    listing.refresh_from_db()
    alias.refresh_from_db()
    assert _listing_state(listing) == listing_before
    assert _alias_state(alias) == alias_before
    assert not _audit_entries(listing).exists()


def test_conflict_can_be_retried_as_confirmation_without_alias(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Retry without changing global alias")
    existing_target = sku_factory(model="Existing target")
    selected_sku = sku_factory(model="Human target")
    alias = _make_alias(existing_target, raw.raw_title)
    alias_before = _alias_state(alias)
    listing = listing_factory(raw_listing=raw)

    conflict = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )
    retry = _post_confirmation(admin_client, listing, selected_sku)

    assert conflict.status_code == 200
    assert retry.status_code == 302
    listing.refresh_from_db()
    alias.refresh_from_db()
    assert listing.sku == selected_sku
    assert listing.resolution_method == "human_confirmed"
    assert _alias_state(alias) == alias_before
    assert SkuAlias.objects.count() == 1


def test_alias_persistence_failure_rolls_back_listing_confirmation(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    listing = listing_factory()
    selected_sku = sku_factory()
    before = _listing_state(listing)

    with patch.object(
        SkuAlias,
        "save",
        autospec=True,
        side_effect=RuntimeError("alias persistence failed"),
    ):
        with pytest.raises(RuntimeError, match="alias persistence failed"):
            _post_confirmation(
                admin_client,
                listing,
                selected_sku,
                create_alias="on",
            )

    listing.refresh_from_db()
    assert _listing_state(listing) == before
    assert SkuAlias.objects.count() == 0
    assert not _audit_entries(listing).exists()


def test_admin_audit_failure_rolls_back_listing_and_created_alias(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    listing = listing_factory()
    selected_sku = sku_factory()
    before = _listing_state(listing)

    def fail_after_alias_exists(*args, **kwargs):
        assert SkuAlias.objects.filter(sku=selected_sku).exists()
        raise RuntimeError("audit failed")

    with patch.object(
        _listing_admin(),
        "log_change",
        side_effect=fail_after_alias_exists,
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            _post_confirmation(
                admin_client,
                listing,
                selected_sku,
                create_alias="on",
            )

    listing.refresh_from_db()
    assert _listing_state(listing) == before
    assert SkuAlias.objects.count() == 0
    assert not _audit_entries(listing).exists()


def test_alias_opt_in_requires_skualias_add_permission(
    client,
    staff_user_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias
    from listings.models import Listing

    user = staff_user_factory()
    _grant(user, Listing, "view", "change")
    client.force_login(user)
    listing = listing_factory()
    before = _listing_state(listing)

    response = _post_confirmation(
        client,
        listing,
        sku_factory(),
        create_alias="on",
    )

    assert response.status_code == 403
    listing.refresh_from_db()
    assert _listing_state(listing) == before
    assert SkuAlias.objects.count() == 0
    assert not _audit_entries(listing).exists()


def test_listing_change_permission_still_allows_confirmation_without_alias(
    client,
    staff_user_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias
    from listings.models import Listing

    user = staff_user_factory()
    _grant(user, Listing, "view", "change")
    client.force_login(user)
    listing = listing_factory()
    selected_sku = sku_factory()

    response = _post_confirmation(client, listing, selected_sku)

    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.sku == selected_sku
    assert listing.resolution_method == "human_confirmed"
    assert SkuAlias.objects.count() == 0


def test_forged_alias_request_cannot_repoint_existing_global_alias(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Protected global alias")
    existing_target = sku_factory(model="Existing")
    selected_sku = sku_factory(model="Selected")
    unrelated_sku = sku_factory(model="Forged")
    alias = _make_alias(existing_target, raw.raw_title)
    before = _alias_state(alias)
    listing = listing_factory(raw_listing=raw)

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
        alias_id=str(alias.pk),
        alias_sku=str(unrelated_sku.pk),
        normalised_text=alias.normalised_text,
    )

    assert response.status_code == 200
    alias.refresh_from_db()
    listing.refresh_from_db()
    assert _alias_state(alias) == before
    assert listing.sku_id is None
    assert SkuAlias.objects.count() == 1


# --- constrained alias administration -----------------------------------


def test_generic_skualias_add_is_disabled(admin_client):
    response = admin_client.get(reverse("admin:catalogue_skualias_add"))

    assert response.status_code == 403


def test_generic_skualias_change_is_blocked_but_evidence_is_viewable(
    admin_client,
    sku_factory,
):
    alias = _make_alias(sku_factory(), "View-only alias")
    before = _alias_state(alias)
    change_url = reverse("admin:catalogue_skualias_change", args=[alias.pk])

    view_response = admin_client.get(change_url)
    change_response = admin_client.post(
        change_url,
        {
            "sku": str(sku_factory().pk),
            "alias_text": "repointed",
            "normalised_text": "repointed",
            "source_of_truth": "human_confirmed",
            "_save": "Save",
        },
    )

    assert view_response.status_code == 200
    assert alias.alias_text in view_response.content.decode()
    assert change_response.status_code == 403
    alias.refresh_from_db()
    assert _alias_state(alias) == before


def test_unused_alias_is_individually_deletable(admin_client, sku_factory):
    from catalogue.models import SkuAlias

    alias = _make_alias(sku_factory(), "Unused deletable alias")

    response = admin_client.post(_alias_delete_url(alias), {"post": "yes"})

    assert response.status_code == 302
    assert not SkuAlias.objects.filter(pk=alias.pk).exists()


def test_alias_supporting_exact_listing_is_individually_protected(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Dependent exact alias")
    sku = sku_factory()
    alias = _make_alias(sku, raw.raw_title)
    listing = listing_factory(raw_listing=raw, sku=sku, resolution_method="exact_alias")

    response = admin_client.post(_alias_delete_url(alias), {"post": "yes"})

    assert response.status_code in {200, 403}
    assert SkuAlias.objects.filter(pk=alias.pk).exists()
    listing.refresh_from_db()
    assert listing.sku == sku
    assert listing.resolution_method == "exact_alias"


def test_protected_alias_bulk_deletion_is_blocked(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Bulk protected alias")
    sku = sku_factory()
    alias = _make_alias(sku, raw.raw_title)
    listing_factory(raw_listing=raw, sku=sku, resolution_method="exact_alias")

    response = _bulk_delete(admin_client, "skualias", [alias.pk])

    assert response.status_code in {200, 403}
    assert SkuAlias.objects.filter(pk=alias.pk).exists()


def test_mixed_alias_bulk_deletion_is_all_or_nothing(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    raw = raw_listing_factory(raw_title="Mixed protected alias")
    protected_sku = sku_factory()
    protected = _make_alias(protected_sku, raw.raw_title)
    listing_factory(
        raw_listing=raw,
        sku=protected_sku,
        resolution_method="exact_alias",
    )
    safe = _make_alias(sku_factory(), "Mixed safe alias")

    response = _bulk_delete(admin_client, "skualias", [protected.pk, safe.pk])

    assert response.status_code in {200, 403}
    assert SkuAlias.objects.filter(pk=protected.pk).exists()
    assert SkuAlias.objects.filter(pk=safe.pk).exists()


def test_unrelated_exact_listing_does_not_block_safe_alias_deletion(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    sku = sku_factory()
    safe_alias = _make_alias(sku, "Alias not used by current result")
    unrelated_raw = raw_listing_factory(raw_title="Different normalized evidence")
    listing_factory(
        raw_listing=unrelated_raw,
        sku=sku,
        resolution_method="exact_alias",
    )

    response = admin_client.post(_alias_delete_url(safe_alias), {"post": "yes"})

    assert response.status_code == 302
    assert not SkuAlias.objects.filter(pk=safe_alias.pk).exists()


def test_user_without_alias_delete_permission_cannot_delete_safe_alias(
    client,
    staff_user_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    user = staff_user_factory()
    _grant(user, SkuAlias, "view")
    client.force_login(user)
    alias = _make_alias(sku_factory(), "Permission protected alias")

    response = client.post(_alias_delete_url(alias), {"post": "yes"})

    assert response.status_code == 403
    assert SkuAlias.objects.filter(pk=alias.pk).exists()


# --- catalogue deletion guardrails --------------------------------------


def test_human_confirmed_sku_deletion_guard_remains_effective(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku

    sku = sku_factory()
    listing_factory(sku=sku, resolution_method="human_confirmed")

    response = admin_client.post(_sku_delete_url(sku), {"post": "yes"})

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()


def test_any_machine_derived_listing_reference_blocks_sku_deletion(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku

    sku = sku_factory()
    listing = listing_factory(sku=sku, resolution_method="exact_alias")

    response = admin_client.post(_sku_delete_url(sku), {"post": "yes"})

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()
    listing.refresh_from_db()
    assert listing.sku == sku


def test_sku_with_alias_reference_is_protected_before_cascade(
    admin_client,
    sku_factory,
):
    from catalogue.models import Sku, SkuAlias

    sku = sku_factory()
    alias = _make_alias(sku, "Curated alias must not cascade")

    response = admin_client.post(_sku_delete_url(sku), {"post": "yes"})

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()
    assert SkuAlias.objects.filter(pk=alias.pk).exists()


def test_mixed_sku_bulk_deletion_is_all_or_nothing(
    admin_client,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku

    protected = sku_factory(model="Protected")
    safe = sku_factory(model="Safe")
    listing_factory(sku=protected, resolution_method="exact_alias")

    response = _bulk_delete(admin_client, "sku", [protected.pk, safe.pk])

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=protected.pk).exists()
    assert Sku.objects.filter(pk=safe.pk).exists()


def test_existing_pricepoint_protection_still_blocks_sku_deletion(
    admin_client,
    sku_factory,
):
    from catalogue.models import Sku
    from pricing.models import PricePoint

    sku = sku_factory()
    PricePoint.objects.create(
        sku=sku,
        condition="used",
        day=date(2026, 1, 1),
        median=Decimal("100.00"),
        p25=Decimal("90.00"),
        p75=Decimal("110.00"),
        n_listings=1,
    )

    response = admin_client.post(_sku_delete_url(sku), {"post": "yes"})

    assert response.status_code in {200, 403}
    assert Sku.objects.filter(pk=sku.pk).exists()


def test_truly_unreferenced_sku_remains_deletable(admin_client, sku_factory):
    from catalogue.models import Sku

    sku = sku_factory()

    response = admin_client.post(_sku_delete_url(sku), {"post": "yes"})

    assert response.status_code == 302
    assert not Sku.objects.filter(pk=sku.pk).exists()


# --- resolver interaction and boundaries --------------------------------


def test_alias_creation_does_not_automatically_resolve_other_listing(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import SkuAlias

    title = "Shared unresolved title RTX 4070 Ti"
    source_listing = listing_factory(
        raw_listing=raw_listing_factory(raw_title=title),
    )
    other_listing = listing_factory(
        raw_listing=raw_listing_factory(raw_title=title),
    )
    other_before = _listing_state(other_listing)

    response = _post_confirmation(
        admin_client,
        source_listing,
        sku_factory(),
        create_alias="on",
    )

    assert response.status_code == 302
    assert SkuAlias.objects.count() == 1
    other_listing.refresh_from_db()
    assert _listing_state(other_listing) == other_before


def test_explicit_operational_rerun_uses_alias_and_preserves_human_source(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from listings.management.commands.resolve_listings import Command

    title = "Shared exact title RX 7900 XT"
    source_listing = listing_factory(
        raw_listing=raw_listing_factory(raw_title=title),
    )
    other_listing = listing_factory(
        raw_listing=raw_listing_factory(raw_title=title),
    )
    selected_sku = sku_factory()

    assert _post_confirmation(
        admin_client,
        source_listing,
        selected_sku,
        create_alias="on",
    ).status_code == 302
    source_listing.refresh_from_db()
    source_state = _listing_state(source_listing)

    Command().handle(verbosity=0)

    source_listing.refresh_from_db()
    other_listing.refresh_from_db()
    assert _listing_state(source_listing) == source_state
    assert other_listing.sku == selected_sku
    assert other_listing.resolution_method == "exact_alias"
    assert other_listing.resolution_confidence == Decimal("1.0000")
    assert other_listing.resolution_method != "fuzzy_match"


def test_alias_confirmation_writes_no_unapproved_downstream_state(
    admin_client,
    raw_listing_factory,
    listing_factory,
    sku_factory,
):
    from catalogue.models import Sku, SkuAlias
    from ingestion.models import Swap
    from outcomes.models import Outcome
    from pricing.models import DealFlag, PricePoint

    raw = raw_listing_factory(raw_title="Boundary alias source")
    listing = listing_factory(raw_listing=raw, condition=None)
    selected_sku = sku_factory()
    raw_before = _raw_state(raw)
    listing_before = _listing_state(listing)
    source_fetch_before = raw.source.last_successful_fetch
    counts_before = {
        "sku": Sku.objects.count(),
        "pricepoint": PricePoint.objects.count(),
        "dealflag": DealFlag.objects.count(),
        "outcome": Outcome.objects.count(),
        "swap": Swap.objects.count(),
    }

    response = _post_confirmation(
        admin_client,
        listing,
        selected_sku,
        create_alias="on",
    )

    assert response.status_code == 302
    raw.refresh_from_db()
    listing.refresh_from_db()
    raw.source.refresh_from_db()
    assert _raw_state(raw) == raw_before
    assert listing.condition == listing_before["condition"]
    assert SkuAlias.objects.count() == 1
    assert Sku.objects.count() == counts_before["sku"]
    assert PricePoint.objects.count() == counts_before["pricepoint"]
    assert DealFlag.objects.count() == counts_before["dealflag"]
    assert Outcome.objects.count() == counts_before["outcome"]
    assert Swap.objects.count() == counts_before["swap"]
    assert raw.source.last_successful_fetch == source_fetch_before


def test_task_018_requires_no_model_or_migration_change(db):
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)
