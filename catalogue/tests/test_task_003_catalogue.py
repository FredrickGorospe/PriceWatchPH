from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction


def test_sku_can_be_created_with_all_fields(db):
    """A Sku can be created with brand, model, variant, category, launch_msrp, launch_date."""
    from catalogue.models import Sku

    sku = Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="OC Edition",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )
    sku.refresh_from_db()
    assert sku.variant == "OC Edition"


def test_sku_brand_model_variant_must_be_unique(db):
    """The database rejects a second Sku row with the same (brand, model, variant)."""
    from catalogue.models import Sku

    Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Sku.objects.create(
                brand="ASUS",
                model="TUF Gaming RTX 4070",
                variant="",
                category="gpu",
                launch_msrp=Decimal("34995.00"),
                launch_date=date(2023, 4, 1),
            )


def test_sku_variant_defaults_to_empty_string_not_null(db):
    """A Sku created without specifying variant stores an empty string, not NULL — NULLs do not collide in the uniqueness index."""
    from catalogue.models import Sku

    sku = Sku.objects.create(
        brand="Corsair",
        model="Vengeance 16GB",
        category="ram",
        launch_msrp=Decimal("2500.00"),
        launch_date=date(2022, 1, 1),
    )
    sku.refresh_from_db()
    assert sku.variant == ""


def test_sku_launch_msrp_must_be_non_negative(db):
    """The database rejects a Sku row with a negative launch_msrp."""
    from catalogue.models import Sku

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Sku.objects.create(
                brand="Test",
                model="Negative MSRP",
                variant="",
                category="cpu",
                launch_msrp=Decimal("-1.00"),
                launch_date=date(2024, 1, 1),
            )


def test_sku_category_must_be_in_vocabulary(db):
    """The database rejects a Sku row whose category is outside the fixed vocabulary."""
    from catalogue.models import Sku

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Sku.objects.create(
                brand="Test",
                model="Bad Category",
                variant="",
                category="not_a_real_category",
                launch_msrp=Decimal("100.00"),
                launch_date=date(2024, 1, 1),
            )


def test_skualias_normalised_text_must_be_unique(db):
    """The database rejects a second SkuAlias row with a normalised_text that already exists."""
    from catalogue.models import Sku, SkuAlias

    sku = Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )
    SkuAlias.objects.create(
        sku=sku,
        alias_text="asus tuf rtx4070",
        normalised_text="asus_tuf_rtx4070",
        source_of_truth="seed",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SkuAlias.objects.create(
                sku=sku,
                alias_text="ASUS TUF RTX 4070 (dup)",
                normalised_text="asus_tuf_rtx4070",
                source_of_truth="human_confirmed",
            )


def test_skualias_source_of_truth_must_be_in_vocabulary(db):
    """The database rejects a SkuAlias row whose source_of_truth is outside the fixed vocabulary."""
    from catalogue.models import Sku, SkuAlias

    sku = Sku.objects.create(
        brand="ASUS",
        model="TUF Gaming RTX 4070",
        variant="",
        category="gpu",
        launch_msrp=Decimal("34995.00"),
        launch_date=date(2023, 4, 1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SkuAlias.objects.create(
                sku=sku,
                alias_text="x",
                normalised_text="x",
                source_of_truth="not_a_real_value",
            )
