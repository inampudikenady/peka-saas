"""Shared password policy for all local authentication flows."""

PLATFORM_PASSWORD_MIN_LENGTH = 12


class PasswordPolicyError(ValueError):
    pass


def validate_platform_password(password: str) -> str:
    if len(password) < PLATFORM_PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {PLATFORM_PASSWORD_MIN_LENGTH} characters."
        )
    return password


validate_local_password = validate_platform_password
