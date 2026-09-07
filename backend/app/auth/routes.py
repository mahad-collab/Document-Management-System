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
import re
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

# Same private-address allowlist as main.py's CORS regex — lets the OAuth
# dance work whether the browser reached this server via localhost or a LAN
# IP (phone/laptop on the same network), without trusting an arbitrary
# Host header for the redirect target (open-redirect guard). Every address
# actually used here must ALSO be added as a Redirect URI in the Entra ID
# App Registration (Entra admin center -> App registrations -> Authentication)
# — Microsoft rejects any redirect_uri it doesn't already know about.
_LOCAL_HOSTS = {"localhost", "127.0.0.1"}
_LAN_HOST_RE = re.compile(
    r"^(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})$"
)


def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.ENTRA_CLIENT_ID,
        client_credential=settings.ENTRA_CLIENT_SECRET,
        authority=settings.ENTRA_AUTHORITY,
    )


def _redirect_uri_for(request: Request) -> str:
    """The backend's own /auth/callback, as reached by THIS request's host —
    not the fixed ENTRA_REDIRECT_URI setting. In development this lets the
    same server accept logins via localhost and via a LAN IP interchangeably,
    provided both are registered redirect URIs in Entra. Falls back to the
    configured static value for any host outside the private allowlist."""
    host = request.url.hostname or ""
    if settings.APP_ENV == "development" and (host in _LOCAL_HOSTS or _LAN_HOST_RE.match(host)):
        port = request.url.port or 8000
        return f"{request.url.scheme}://{host}:{port}/auth/callback"
    return settings.ENTRA_REDIRECT_URI


def _frontend_url_for(request: Request) -> str:
    """Where to send the browser after a successful login — the frontend
    dev server on the SAME host the user actually reached this backend on,
    so a LAN device lands back on a frontend it can actually reach (not
    this machine's own localhost).

    Scheme/port depend on which host reached us, and this MUST match
    whatever scheme the session cookie was set under: Chrome's "schemeful
    same-site" rule treats http and https on the same hostname as
    different sites, so a cookie set by an https:// response won't ride
    along on a fetch() from an http:// page. localhost keeps the plain-HTTP
    dev server on :3000 (matches the plain-HTTP backend on :8000); a LAN IP
    goes to the HTTPS frontend instance on :3443 (matches the HTTPS backend
    on :8443, both using the same self-signed cert in backend/certs/)."""
    host = request.url.hostname or ""
    if settings.APP_ENV != "development":
        return settings.FRONTEND_URL
    if host in _LOCAL_HOSTS:
        return f"http://{host}:3000"
    if _LAN_HOST_RE.match(host):
        return f"https://{host}:3443"
    return settings.FRONTEND_URL


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
        redirect_uri=_redirect_uri_for(request),
        # Forces Microsoft to show its actual login prompt every time,
        # instead of silently completing via an existing browser SSO
        # session (which is otherwise valid/expected behavior, but not
        # what's wanted when specifically verifying the login screen
        # itself — e.g. demoing/testing the auth flow with someone new).
        prompt="login",
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
        redirect_uri=_redirect_uri_for(request),
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
    #
    # A Super Admin can also pre-provision a user (email + display name,
    # entra_object_id left NULL — see app/users/routes.py's create_user) so
    # roles can be assigned before that person ever signs in. On their
    # actual first login there's no entra_object_id match yet, so fall back
    # to an email lookup; if that hits a pre-provisioned row, backfill the
    # real oid onto it instead of creating a second row with the same email
    # (which would fail on the unique constraint).
    stmt = select(User).where(User.entra_object_id == entra_object_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        stmt = select(User).where(User.email == email, User.entra_object_id.is_(None))
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.entra_object_id = entra_object_id

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
    return RedirectResponse(url=_frontend_url_for(request))


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
