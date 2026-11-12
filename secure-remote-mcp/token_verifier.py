"""token_verifier.py - validates JWT access tokens for an MCP resource server."""
import asyncio
import logging

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

log = logging.getLogger("mcp.auth")


class JwksTokenVerifier(TokenVerifier):
    """Accepts a token only if it was signed by the expected issuer AND minted for this server."""

    def __init__(self, issuer: str, audiences: list[str], jwks_uri: str) -> None:
        self._issuer = issuer
        self._audiences = audiences
        # Signing keys are cached and re-fetched on an unknown key id, which covers key rotation.
        self._jwks = PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600, timeout=5)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # PyJWKClient does blocking I/O on a cache miss; keep it off the event loop.
            claims = await asyncio.to_thread(self._decode, token)
        except jwt.PyJWTError as exc:
            # Log the reason, never the token.
            log.warning("token rejected: %s", type(exc).__name__)
            return None

        # Authorization servers disagree on the claim name: 'scope' (RFC 9068) or 'scp' (Entra ID).
        scopes = str(claims.get("scope") or claims.get("scp") or "").split()
        client_id = claims.get("client_id") or claims.get("azp") or claims.get("appid") or "unknown"
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            subject=str(claims["sub"]),
            claims={"iss": claims["iss"], "aud": claims["aud"]},
        )

    def _decode(self, token: str) -> dict:
        key = self._jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],            # pinned: never read the algorithm from the token
            issuer=self._issuer,
            audience=self._audiences,        # the audience check is what stops token reuse
            options={"require": ["exp", "iss", "aud", "sub"]},
            leeway=30,
        )
