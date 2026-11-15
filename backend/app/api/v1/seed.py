from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import normalize_role
from app.core.security import get_current_user
from app.models.workspace import Organization, User
from app.services.synthetic_demo_data import seed_synthetic_demo_data

router = APIRouter(prefix="/seed", tags=["Demonstration Seeder"])


@router.post("/demo")
def seed_demo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly initialize an isolated Demo Workspace (marked is_demo=True) for evaluation. Requires admin authorization."""
    if not settings.ENABLE_DEMO_SEED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo seeding is disabled in this environment.",
        )

    # Require proper administrator authorization
    org = db.query(Organization).filter(Organization.id == current_user.org_id).first() if current_user.org_id else None
    is_admin = (
        normalize_role(current_user.role) in ("org_admin", "admin")
        or (org is not None and org.owner_id == current_user.id)
    )
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only administrators or organization owners can seed demonstration data.",
        )

    return seed_synthetic_demo_data(db=db, owner_user=current_user)
