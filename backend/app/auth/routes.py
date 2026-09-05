"""
Microsoft Entra ID authentication — backend-for-frontend pattern.

Flow (spec Section 6):
  Employee -> /auth/login -> redirected to Microsoft login
  Microsoft -> /auth/callback (auth code) -> backend exchanges code for tokens
  Backend creates its OWN session (signed cookie) -> frontend never sees
  Entra access/refresh tokens directly.

Why this pattern over handing tokens to the SPA: Section 25 explicitly
prohibits exposing Microsoft access tokens to the frontend. MSAL's
confidential client (using ENTRA_CLIENT_SECRET) runs only on the backend.
"""
import uuid

import msal
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditResult
from app.audit.service import log_audit
from app.auth.rbac import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ENTRA_CLIENT_ID,
        client_credential=settings.ENTRA_CLIENT_SECRET,
        authority=settings.ENTRA_AUTHORITY,
    )


@router.get("/login")
async def login(request: Request):
    """Redirects the browser to Microsoft's login page."""
    msal_app = _msal_app()
    # A per-login random state value, checked on callback, mitigates CSRF
    # against the OAuth redirect (spec Section 25: CSRF protection).
    state = str(uuid.uuid4())
    request.session["oauth_state"] = state

    auth_url = msal_app.get_authorization_request_url(
        scopes=settings.ENTRA_SCOPES.split(),
        state=state,
        redirect_uri=settings.ENTRA_REDIRECT_URI,
    )
    return RedirectResponse(auth_url)


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: AsyncSession = Depends(get_db)):
    """Exchanges the auth code for tokens, then maps the Entra identity to a DMS user."""
    if state != request.session.get("oauth_state"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")

    msal_app = _msal_app()
    result = msal_app.acquire_token_by_authorization_code(
        code=code,
        scopes=settings.ENTRA_SCOPES.split(),
        redirect_uri=settings.ENTRA_REDIRECT_URI,
    )

    if "error" in result:
        await log_audit(
            action=AuditAction.LOGIN,
            result=AuditResult.FAILURE,
            details=f"Entra ID error: {result.get('error_description', result['error'])}",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Entra ID authentication failed: {result.get('error_description', result['error'])}",
        )

    claims = result.get("id_token_claims", {})
    entra_object_id = claims.get("oid")
    email = claims.get("preferred_username") or claims.get("email")
    display_name = claims.get("name", email)

    if not entra_object_id or not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Entra ID token missing required claims")

    # First login provisions the DMS user record; subsequent logins just
    # refresh display attributes. Role/department assignment is a separate
    # admin action (Section 7) — a brand-new user has NO roles by default.
    stmt = select(User).where(User.entra_object_id == entra_object_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        user = User(entra_object_id=entra_object_id, email=email, display_name=display_name)
        db.add(user)
    else:
        existing.email = email
        existing.display_name = display_name
        user = existing

    await db.commit()
    await db.refresh(user)

    if not user.is_active:
        await log_audit(action=AuditAction.LOGIN, result=AuditResult.FAILURE, user_id=user.id, details="Account is disabled")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")

    # The DMS session is our own — no Entra token is ever stored here or
    # sent to the browser. This cookie is signed + httpOnly (see main.py).
    request.session["user_id"] = str(user.id)
    request.session.pop("oauth_state", None)

    await log_audit(action=AuditAction.LOGIN, result=AuditResult.SUCCESS, user_id=user.id)

    # The backend has no UI of its own — send the browser to the actual
    # frontend app once the session cookie is set.
    return RedirectResponse(url=settings.FRONTEND_URL)


@router.get("/me")
async def me(current_user: CurrentUser = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "display_name": current_user.display_name,
        "is_super_admin": current_user.is_super_admin,
        "departments": [str(dept_id) for dept_id in current_user.department_permissions.keys()],
    }


@router.post("/logout")
async def logout(request: Request, current_user: CurrentUser = Depends(get_current_user)):
    await log_audit(action=AuditAction.LOGOUT, result=AuditResult.SUCCESS, user_id=current_user.id)
    request.session.clear()
    return {"detail": "Logged out"}
