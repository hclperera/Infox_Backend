# Feature 2: mobile sessions

## Deployment and verification

Apply `db/migrate_user_sessions.sql` to the existing MySQL database before starting this backend version. Use the existing database administration process and take a backup first. Do not rerun the full schema against an existing database. New installations use `db/schema.sql`.

Deploy the backend and updated mobile client together: older clients do not supply the bearer credentials now required for settings, scans, and profile changes. Existing mobile users must log in once after upgrading. No new signing secret is required; random opaque credentials are issued and only SHA-256 token digests are stored in MySQL. Passwords remain bcrypt hashes on the server.

Access credentials expire after 30 minutes. Refresh credentials rotate on renewal and expire 30 days after login; renewal does not extend that deadline. Logout revokes the current session; password changes revoke every session for that user. Deleting a user cascades to their sessions. Password-reset revocation must also be wired into the upcoming password-recovery feature.

Automated check: `python -m unittest tests.test_registration_validation tests.test_auth_sessions -v` (11 tests passed). These exercise actual routes against an isolated SQLite adapter, not production MySQL. The user confirmed a successful database backup and creation of the session table on the server. Deployed API behavior, MySQL locking behavior, and device integration still require verification.

After migration and deployment, verify login, `/auth/me`, refresh rotation, logout, settings, scan upload/polling and password change from the updated app. Requests without a bearer token must return 401; attempting another user's settings must return 403 and another user's scan must return 404. Check that logout invalidates the old credentials and password changes invalidate another device's session on its next request. Never paste credentials into shared logs or commit them.

## Commit prepared for the user

Title: `feat(auth): add revocable mobile sessions and protect user endpoints`

Body:

- Issue random access and refresh credentials at login, persisting only token digests.
- Expire access after 30 minutes and rotate refresh credentials within a fixed 30-day session.
- Add authenticated profile lookup, refresh, and idempotent logout endpoints.
- Require bearer authentication and ownership checks for settings, profile changes, scan upload, and scan polling.
- Revoke all user sessions after password changes and cascade session removal on account deletion.
- Prevent authentication-response caching and preserve exact password input.
- Add a MySQL migration, fresh-install schema, and route-level regression tests.
- Validate registration and session behavior with 11 passing isolated tests; deployed API and device integration testing remain pending.

Include only these files:

- `db/schema.sql`
- `db/migrate_user_sessions.sql`
- `routers/auth.py`
- `routers/braille.py`
- `routers/settings.py`
- `schemas.py`
- `services/sessions.py`
- `tests/test_auth_sessions.py`
- `SESSION_AUTH.md`

Other existing untracked guides and dataset scripts belong to separate work. No commit or deployment was performed by the assistant.
