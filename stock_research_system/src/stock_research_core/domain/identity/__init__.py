"""FinQuest identity/authentication domain: enums and models with no
infrastructure dependencies (no SQLAlchemy, FastAPI, PyJWT, pwdlib, or
any HTTP library). A `UserAccount` is a distinct identity concept from
`domain.learning.models.LearnerProfile` - it references a learner by
UUID only and never carries a password hash, access token, refresh
token, or signing key.
"""
