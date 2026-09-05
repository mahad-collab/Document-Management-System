"""
SharePoint/Graph API error types.

Kept distinct from a generic HTTPException so calling code (and audit
logging, per Section 34: "SharePoint failures" must be logged) can tell
"the app registration's credentials are wrong" apart from "this specific
folder doesn't exist" apart from "Graph rate-limited us, retry later."
"""


class SharePointError(Exception):
    """Base class for all SharePoint/Graph integration failures."""


class SharePointAuthError(SharePointError):
    """Failed to acquire an app-only Graph token, or the token was rejected."""


class SharePointNotFoundError(SharePointError):
    """The referenced site/drive/item does not exist (Graph returned 404)."""


class SharePointConflictError(SharePointError):
    """The operation conflicts with existing state (e.g. name already exists, Graph 409)."""


class SharePointRateLimitedError(SharePointError):
    """Graph returned 429 — caller should retry after the given delay."""

    def __init__(self, retry_after_seconds: float, message: str = "Graph API rate limit exceeded"):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
