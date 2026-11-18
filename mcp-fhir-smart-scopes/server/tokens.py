"""Verify the access token and carry its SMART context to the tools."""
from __future__ import annotations

import time

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier


class SmartToken(AccessToken):
    """An access token plus the two SMART facts the tools need."""

    subject: str = ""
    patient: str | None = None  # the patient in context, for patient/ scopes


class JwtVerifier(TokenVerifier):
    """Signature, issuer, audience and expiry, checked here. Scopes are checked per tool call."""

    def __init__(self, public_key: str, issuer: str, audience: str) -> None:
        self.public_key, self.issuer, self.audience = public_key, issuer, audience

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],  # never taken from the token header
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError:
            return None
        if claims["exp"] <= time.time():
            return None
        return SmartToken(
            token=token,
            client_id=claims.get("client_id", claims["sub"]),
            scopes=str(claims.get("scope", "")).split(),
            expires_at=int(claims["exp"]),
            resource=self.audience,
            subject=claims["sub"],
            patient=claims.get("patient"),
        )
