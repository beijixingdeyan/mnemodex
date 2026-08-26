"""Auth token API: issue and validate short-lived session tokens."""

import secrets

from .cache import TokenCache

# Single shared cache. Gotcha: tokens expire after 60s (its ttl_seconds).
_cache = TokenCache()


def issue_token(username):
    """Return a fresh token for username, evicting any previous one."""
    token = secrets.token_hex(16)
    _cache.put(username, token)
    return token


def validate(token):
    """True iff token is cached and still inside its 60s TTL."""
    for username, stored in _cache._data.items():
        if stored == token:
            return _cache.get(username) == token
    return False