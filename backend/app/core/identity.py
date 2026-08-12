def normalize_email(email: str) -> str:
    """Return the canonical email representation used for identity lookups."""
    return email.strip().lower()
