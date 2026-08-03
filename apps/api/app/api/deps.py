"""Shared API dependencies and small fetch helpers."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, Email, Factory, Product, SenderAccount, User
from app.security import CurrentUser, assert_factory_access

DbDep = Annotated[Session, Depends(get_db)]


def get_owned_sender_account(account_id: uuid.UUID, db: DbDep, user: CurrentUser) -> SenderAccount:
    """Fetch a sender account only if it belongs to the caller's factory.

    Tenant isolation for mailboxes: a factory user can only reach their own
    connected accounts; staff (admin/analyst) may reach any.
    """
    account = db.get(SenderAccount, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Sender account not found"
        )
    assert_factory_access(user, account.factory_id)
    return account


def get_owned_product(product_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    assert_factory_access(user, product.factory_id)
    return product


def get_owned_campaign(campaign_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    assert_factory_access(user, campaign.factory_id)
    return campaign


def get_owned_email(email_id: uuid.UUID, db: DbDep, user: CurrentUser) -> Email:
    email = db.get(Email, email_id)
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email not found")
    campaign = db.get(Campaign, email.campaign_id)
    assert_factory_access(user, campaign.factory_id)
    return email


def resolve_factory(db: Session, user: User) -> Factory:
    if user.factory_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is not linked to a factory",
        )
    factory = db.get(Factory, user.factory_id)
    if factory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return factory
