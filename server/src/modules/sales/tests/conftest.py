"""Factories for the sales-control tests (fixtures for this package only).

CONVENTIONS.md §13: test data is created only through a factory. These live
beside the module rather than in ``conftest.py`` because nothing outside
``modules/sales`` has a use for them — the same decision the analysis tests
made for their own helpers.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.sales.models import (
    SaleBranchModel,
    SaleModel,
    SalePartnerModel,
    SaleReviewModel,
)
from src.modules.sales.rules import SaleOpType, matchable_phone
from src.modules.settings.models import AppSettingModel

#: A date well inside a working month, far from any month boundary.
SALE_DAY = date(2026, 8, 20)


@pytest.fixture
def set_sales_setting(db: AsyncSession) -> Callable[..., Any]:
    """Change one seeded ``app_settings`` row, as the analysis tests do it.

    Every threshold in this module is a row rather than a constant (SPEC §3.8),
    so a test that wants a different window or a different shared-code list
    changes the row — it never passes the value in around the settings layer.
    """

    async def _set(key: str, value: Any) -> None:
        row = await db.get(AppSettingModel, key)
        assert row is not None, f"{key} is not seeded — migration 014 did not run"
        row.value = value
        await db.flush()

    return _set


@pytest.fixture
def partner_factory(db: AsyncSession) -> Callable[..., Any]:
    """A SAP contractor. ``phone_key`` is GENERATED, so the row is refreshed."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> SalePartnerModel:
        counter["n"] += 1
        phone = overrides.pop("phone", f"+99890111{counter['n']:04d}")
        partner = SalePartnerModel(
            # ⚠️ Deliberately far from `К00001`: that code is a SHARED one and a
            # partner minted with it would silently leave the regular-customer
            # section, which is exactly the kind of invisible miscount this
            # module exists to prevent. The letter is CYRILLIC К (U+041A).
            code=overrides.pop("code", f"К8{counter['n']:04d}"),
            name=overrides.pop("name", f"Mijoz {counter['n']}"),
            group_name=overrides.pop("group_name", "Клиенты"),
            phone=phone,
            # Written by the importer through the same rule, so a test cannot
            # accidentally give a partner a key the importer would refuse.
            matchable_phone=overrides.pop("matchable_phone", matchable_phone(phone)),
            **overrides,
        )
        db.add(partner)
        await db.flush()
        await db.refresh(partner)
        return partner

    return _create


@pytest.fixture
def sale_factory(db: AsyncSession) -> Callable[..., Any]:
    """One SAP operation. Defaults to a sale on :data:`SALE_DAY`."""
    counter = {"n": 0}

    async def _create(**overrides: Any) -> SaleModel:
        counter["n"] += 1
        partner = overrides.pop("partner", None)
        amount = overrides.pop("amount_usd", Decimal("100.000"))
        sale = SaleModel(
            external_id=overrides.pop("external_id", f"OP{counter['n']:06d}"),
            op_type=overrides.pop("op_type", SaleOpType.SALE.value),
            occurred_on=overrides.pop("occurred_on", SALE_DAY),
            partner_code=overrides.pop(
                "partner_code", partner.code if partner else "К00404"
            ),
            partner_name=overrides.pop(
                "partner_name", partner.name if partner else None
            ),
            currency=overrides.pop("currency", "USD"),
            amount=overrides.pop("amount", amount),
            amount_usd=amount,
            **overrides,
        )
        db.add(sale)
        await db.flush()
        await db.refresh(sale)
        return sale

    return _create


@pytest.fixture
def sale_branch_factory(db: AsyncSession) -> Callable[..., Any]:
    """One row of the branch map."""

    async def _create(branch: str, **overrides: Any) -> SaleBranchModel:
        row = SaleBranchModel(branch=branch, **overrides)
        db.add(row)
        await db.flush()
        return row

    return _create


@pytest.fixture
def sale_review_factory(db: AsyncSession) -> Callable[..., Any]:
    """A decision already recorded against a sale."""

    async def _create(sale_id: uuid.UUID, **overrides: Any) -> SaleReviewModel:
        row = SaleReviewModel(
            sale_id=sale_id, status=overrides.pop("status", "justified"), **overrides
        )
        db.add(row)
        await db.flush()
        return row

    return _create
