from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import CurrentUser, DatabaseSession, PlatformAdmin, VerifiedUser
from app.modules.organizers import payouts
from app.modules.organizers import service as organizer_service
from app.modules.organizers.schemas import (
    IdentityVerificationCreate,
    MyOrganizerProfileResponse,
    OrganizerProfileCreate,
    OrganizerProfileResponse,
    OrganizerProfileUpdate,
    OrganizerVerificationUpdate,
    PayoutAccountResponse,
    PayoutAccountUpsert,
    my_profile_response,
    payout_response,
)

router = APIRouter(prefix="/organizers", tags=["Organizers"])


@router.post(
    "/", response_model=OrganizerProfileResponse, status_code=status.HTTP_201_CREATED
)
async def create_organizer_profile(
    user: VerifiedUser,
    db: DatabaseSession,
    data_in: OrganizerProfileCreate | None = None,
):
    """Create the signed-in user's organizer profile (verified email required).

    The body is optional; ``display_name`` defaults to the user's full name.
    Creating a first event also creates the profile automatically.
    """
    return await organizer_service.create_organizer_profile(
        db=db,
        user=user,
        data_in=data_in if data_in is not None else OrganizerProfileCreate(),
    )


@router.get("/me", response_model=MyOrganizerProfileResponse)
async def get_my_profile(user: CurrentUser, db: DatabaseSession):
    return my_profile_response(await organizer_service.get_my_profile(db=db, user=user))


@router.patch("/me", response_model=MyOrganizerProfileResponse)
async def update_my_profile(
    data_in: OrganizerProfileUpdate, user: CurrentUser, db: DatabaseSession
):
    return my_profile_response(
        await organizer_service.update_my_profile(db=db, user=user, data_in=data_in)
    )


@router.post("/me/verification", response_model=MyOrganizerProfileResponse)
async def submit_identity_verification(
    data_in: IdentityVerificationCreate, user: CurrentUser, db: DatabaseSession
):
    """Simulated identity check for paid sales (SRS 3.2).

    A valid IIN/BIN verifies the organizer at once. If an admin rejected the
    organizer before, the submission waits for an admin instead.
    """
    return my_profile_response(
        await payouts.submit_identity(db=db, user=user, data_in=data_in)
    )


@router.get("/me/payout-account", response_model=PayoutAccountResponse)
async def get_payout_account(user: CurrentUser, db: DatabaseSession):
    return payout_response(await payouts.get_my_payout_account(db=db, user=user))


@router.put("/me/payout-account", response_model=PayoutAccountResponse)
async def save_payout_account(
    data_in: PayoutAccountUpsert,
    user: CurrentUser,
    db: DatabaseSession,
    background: BackgroundTasks,
):
    """Save the account ticket revenue would be paid to. Simulated: a valid
    Kazakhstan IBAN counts as verified; no money is ever sent. The IBAN is
    only ever shown masked."""
    return payout_response(
        await payouts.upsert_payout_account(
            db=db, user=user, data_in=data_in, background=background
        )
    )


@router.get("/{id}", response_model=OrganizerProfileResponse)
async def get_organizer_profile(id: UUID, db: DatabaseSession):
    return await organizer_service.get_organizer_profile(db=db, id=id)


@router.patch("/{id}/verification", response_model=OrganizerProfileResponse)
async def set_verification(
    id: UUID,
    data_in: OrganizerVerificationUpdate,
    admin: PlatformAdmin,
    db: DatabaseSession,
):
    """Platform admins only."""
    return await organizer_service.set_verification(
        db=db,
        id=id,
        verification_status=data_in.verification_status,
        admin=admin,
    )
