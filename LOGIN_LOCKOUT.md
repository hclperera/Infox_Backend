# Feature 3: server-enforced login lockout

Five consecutive incorrect passwords for an existing account lock new logins for 15 minutes. The fifth failure and requests during the lock return HTTP 429 with a `Retry-After` header in seconds. Correct passwords cannot bypass an active lock. Attempts during a lock do not extend its deadline. After expiry, failures start from zero; successful login clears the counter.

State is keyed by user ID in MySQL, so app restarts, username changes and multiple Uvicorn workers cannot reset the counter. The login transaction locks the user row before reading or updating the counter. Unknown usernames return the same generic 401 as other invalid credentials without creating database records. Request validation errors and server failures do not increment the counter. A request that reaches the backend with an incorrect password still counts if its response is lost in transit. Existing authenticated sessions remain usable during a login lock.

## Deployment

1. Make a fresh database backup with a new filename; retain the previous backup.
2. Apply only `db/migrate_login_lockout.sql` to the existing database. Confirm the `login_security` table exists. Do not rerun the full schema.
3. Review and commit the backend files below on a feature branch, suggested `codex/login-lockout`, and push using your account.
4. Ensure the cron deployment pulls that branch and restarts Uvicorn. Confirm the deployed commit before testing.
5. Install the matching updated APK and perform the app guide's device checks before its commit.

The table is initially empty; failed logins create rows. Password recovery is a separate feature and should clear this state after a verified password reset. This feature implements per-account lockout, not general IP-based rate limiting or admin-panel authentication.

## Validation

All 14 backend tests passed using `python -m unittest tests.test_registration_validation tests.test_auth_sessions -v`. New coverage includes the fifth-failure threshold, a correct-password bypass attempt from a second HTTP client, decreasing retry time, account independence, expiry, reset after success, and failure rollback. Tests use isolated SQLite; deployed MySQL migration and concurrent row-lock behavior are not verified by this suite. Device testing is pending.

## Backend commit

Title: `feat(auth): enforce account login lockout on the server`

Body:

- Persist failed password attempts and lock deadlines per account in MySQL.
- Lock new logins for 15 minutes after five consecutive incorrect passwords.
- Serialize attempts using the existing user-row transaction lock across API workers.
- Return HTTP 429 and remaining Retry-After seconds without extending active locks.
- Reset failure state after successful authentication or an expired lock.
- Keep unknown-user errors generic and avoid counting validation or server failures.
- Add an incremental migration and update the fresh-install database schema.
- Validate lockout and existing authentication behavior with 14 passing isolated tests; deployed MySQL and device checks remain pending.

Include exactly:

- `db/schema.sql`
- `db/migrate_login_lockout.sql`
- `routers/auth.py`
- `tests/test_auth_sessions.py`
- `LOGIN_LOCKOUT.md`

Do not include unrelated guides, dataset scripts, backups, or credentials. The assistant has not committed, pushed, migrated, or deployed these changes.
