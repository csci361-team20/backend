"""Organizer identity verification and payout account (SRS 3.2, 4.1, 4.5).

Both are simulations for the academic MVP: identity is "verified" when the
IIN/BIN is well formed, the payout account when the IBAN is well formed.
No KYC provider or bank is contacted, and no money is ever paid out.
"""

from datetime import UTC, datetime

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.kz_ids import normalize_iban
from app.modules.audit import service as audit
from app.modules.audit.enums import AuditAction, AuditEntity
from app.modules.notifications.service import notify
from app.modules.organizers import service as organizer_service
from app.modules.organizers.models import OrganizerProfile, PayoutAccount
from app.modules.organizers.schemas import (
    IdentityVerificationCreate,
    PayoutAccountUpsert,
    VerificationStatus,
)
from app.modules.users.models import User


async def submit_identity(
    db: AsyncSession, user: User, data_in: IdentityVerificationCreate
) -> OrganizerProfile:
    profile = await organizer_service.get_my_profile(db, user)
    now = datetime.now(UTC)
    profile.legal_name = data_in.legal_name
    profile.tax_id = data_in.tax_id
    profile.verification_submitted_at = now
    if profile.verification_status == VerificationStatus.REJECTED:
        # An admin turned this organizer down; only an admin can approve again
        profile.verification_status = VerificationStatus.PENDING
        outcome = "resubmitted for admin review"
    else:
        profile.verification_status = VerificationStatus.VERIFIED
        profile.verified_at = now
        outcome = "verified (simulated)"
    audit.record(
        db,
        actor=user,
        action=AuditAction.ORGANIZER_IDENTITY_SUBMITTED,
        entity_type=AuditEntity.ORGANIZER_PROFILE,
        entity_id=profile.id,
        description=f"Identity details submitted; {outcome}",
        details={"status": profile.verification_status},
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def get_payout_account(db: AsyncSession, profile_id) -> PayoutAccount | None:
    result = await db.execute(
        select(PayoutAccount).where(PayoutAccount.organizer_profile_id == profile_id)
    )
    return result.scalar_one_or_none()


async def get_my_payout_account(db: AsyncSession, user: User) -> PayoutAccount:
    profile = await organizer_service.get_my_profile(db, user)
    account = await get_payout_account(db, profile.id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No payout account yet")
    return account


async def upsert_payout_account(
    db: AsyncSession,
    user: User,
    data_in: PayoutAccountUpsert,
    background: BackgroundTasks | None = None,
) -> PayoutAccount:
    profile = await organizer_service.get_my_profile(db, user)
    account = await get_payout_account(db, profile.id)
    now = datetime.now(UTC)
    values = {
        "holder_name": data_in.holder_name,
        "bank_name": data_in.bank_name,
        "iban": normalize_iban(data_in.iban),
        # The schema only accepts well-formed IBANs, so the simulation passes
        "is_verified": True,
        "verified_at": now,
    }
    if account is None:
        account = PayoutAccount(organizer_profile_id=profile.id, **values)
        db.add(account)
    else:
        for field, value in values.items():
            setattr(account, field, value)
    audit.record(
        db,
        actor=user,
        action=AuditAction.PAYOUT_ACCOUNT_SAVED,
        entity_type=AuditEntity.PAYOUT_ACCOUNT,
        entity_id=profile.id,
        description=f"Payout account saved ({data_in.bank_name}, verified, simulated)",
    )
    if background is not None:
        # "Organizer payout status" (SRS 4.10)
        notify(db, background, [user], "payout_saved", bank=data_in.bank_name)
    await db.commit()
    await db.refresh(account)
    return account
