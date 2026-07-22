"""Request/response DTOs for the FinQuest API.

Plain `pydantic.BaseModel` subclasses (not `domain.models.DomainModel`)
with `extra="forbid"` - deliberately separate from every domain/ORM
model so a router's explicit field-by-field mapping is the only way
data crosses the transport boundary. This is what structurally
guarantees a password hash, a refresh-token hash, a correct-answer
flag, a hidden scenario outcome, or a raw retrieval vector can never
leak into a response.
"""
