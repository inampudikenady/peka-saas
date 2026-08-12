# Recovering a Platform Administrator

This is an emergency, local-access procedure for resetting the password of an
existing `platform_admin` account. It is not exposed through the frontend or
HTTP API, does not create accounts, and cannot change roles or promote a
`platform_readonly` account.

## Procedure

1. Activate the backend environment:

   ```bash
   cd backend
   source .venv/bin/activate
   ```

2. Run recovery using one exact account identifier:

   ```bash
   python -m app.cli platform-admin reset-password \
     --email admin@example.com
   ```

   Username selection is also supported:

   ```bash
   python -m app.cli platform-admin reset-password \
     --username platformadmin
   ```

3. Verify the displayed username, email, role, active state, and lock state.
4. Confirm the reset. The default response is No.
5. Enter and confirm the new password at the hidden prompts. The password must
   satisfy the same policy as the web reset flow.
6. Test Platform Admin login with the new password. A backend restart is not
   required.
7. Confirm the old password no longer works and the Platform ReadOnly account
   remains unchanged.

Never put a password in a command argument, shell script, terminal history, or
operational notes. The CLI intentionally has no `--password` option. `--yes`
may skip only the account confirmation; it never bypasses the hidden password
prompts.

## Security and audit behavior

- The command uses normal application settings, SQLAlchemy `SessionLocal`, the
  configured database, the existing Platform Admin repository, and the
  application Argon2 password hasher.
- It activates and unlocks only the selected existing Platform Admin and resets
  failed login attempts. It does not modify the role.
- It logs `platform_admin_password_recovered` with the recovered user ID,
  username, email, timestamp, and `command_source=local_cli`.
- Passwords, hashes, tokens, database URLs, and credentials are never printed
  or logged.
- Platform authentication uses stateless JWTs and currently has no token
  revocation store. Tokens issued before recovery remain valid until their
  configured expiration. This recovery command does not add a separate session
  mechanism.

Treat every use as an emergency operational event and record it through the
organization's normal incident/change-management process.
