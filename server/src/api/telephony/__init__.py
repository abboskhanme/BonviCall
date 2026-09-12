"""The provider-facing surface (T-MZ).

A fourth audience, and the only one that is not ours: MoiZvonki's servers POST
call events here. It is deliberately its own package rather than a corner of
``service/`` — the authentication is different (a secret in the path, because
the caller holds no credential of ours), the contract belongs to somebody else,
and it must never be able to reach a route that expects one of our principals.
"""

from src.api.telephony.webhook import router

__all__ = ["router"]
