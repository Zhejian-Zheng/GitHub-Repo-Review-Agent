"""HTTP policy for requests carrying provider or service credentials."""
from __future__ import annotations

from typing import BinaryIO
from urllib.request import HTTPRedirectHandler, build_opener


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # urllib otherwise copies Authorization and apikey headers to the redirect
        # destination. Service endpoints are exact URLs; fail closed on redirects.
        return None


_CREDENTIAL_OPENER = build_opener(_RejectRedirects())


def credential_urlopen(request, *, timeout):
    """Open an exact credential-bearing endpoint without following redirects."""
    return _CREDENTIAL_OPENER.open(request, timeout=timeout)


class ResponseTooLargeError(ValueError):
    """The upstream body exceeded the configured byte limit."""


def read_response_bytes(response: BinaryIO, *, limit: int = 8_000_000) -> bytes:
    """Read at most limit + 1 bytes, including streams that return short reads."""
    if limit < 0:
        raise ValueError("Response byte limit must be nonnegative.")
    body = bytearray()
    while len(body) <= limit:
        chunk = response.read(min(65_536, limit + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
    raise ResponseTooLargeError("Response exceeded its byte limit.")
