from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.workspace import User
from app.services.synthetic_demo_data import seed_synthetic_demo_data

router = APIRouter(prefix="/seed", tags=["Demonstration Seeder"])


@router.post("/demo")
def seed_demo(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly initialize an isolated Demo Workspace (marked is_demo=True) for evaluation."""
    return seed_synthetic_demo_data(db=db, owner_user=current_user)
