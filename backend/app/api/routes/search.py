from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, raise_authz
from app.db.session import get_db
from app.models import User
from app.services.authorization import AuthorizationError
from app.services.search import MAX_QUERY_LENGTH, MAX_RESULTS, scoped_search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    q: str = Query("", max_length=MAX_QUERY_LENGTH * 2),
    limit: int = Query(MAX_RESULTS, ge=1, le=MAX_RESULTS),
    session: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Authorised organisation units and indicators matching a literal query. Read-only."""
    try:
        return scoped_search(session, user, q, limit=limit)
    except AuthorizationError as error:
        raise_authz(error)
