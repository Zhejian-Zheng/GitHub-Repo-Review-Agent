"""HTTP policy for requests carrying provider or service credentials."""
from __future__ import annotations

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
