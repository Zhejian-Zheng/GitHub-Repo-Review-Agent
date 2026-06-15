from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {"id": self.id, "email": self.email}


def bearer_token_from_headers(headers) -> str | None:
    authorization = headers.get("authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    return token or None


def get_supabase_user(
    access_token: str,
    *,
    supabase_url: str | None = None,
    anon_key: str | None = None,
    timeout: float = 10,
) -> AuthUser:
    resolved_url = supabase_url or os.environ.get("SUPABASE_URL")
    resolved_key = (
        anon_key
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
    )
    if not resolved_url:
        raise AuthError("SUPABASE_URL is required to verify authenticated users.")
    if not resolved_key:
        raise AuthError("SUPABASE_ANON_KEY is required to verify authenticated users.")

    request = Request(
        f"{resolved_url.rstrip('/')}/auth/v1/user",
        headers={
            "apikey": resolved_key,
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload: Any = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AuthError(f"Supabase auth rejected the access token ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise AuthError(f"Supabase auth verification failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise AuthError("Supabase auth returned invalid JSON.") from exc

    user_id = payload.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise AuthError("Supabase auth response did not include a user id.")
    email = payload.get("email") if isinstance(payload.get("email"), str) else None
    return AuthUser(id=user_id, email=email)
