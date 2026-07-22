"""Concrete, replaceable infrastructure adapters for identity/authentication:
Argon2id password hashing, JWT access tokens, opaque refresh tokens,
and a process-local rate limiter. None of these modules connects to a
database, makes a network request, or does expensive work at import
time - importing this package is always cheap and side-effect-free.
"""
