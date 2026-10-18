# Feature 4: password recovery with Resend

An eight-digit email code expires after 10 minutes, works once, and allows at most five incorrect submissions. Requests are limited per account to one per 60 seconds and five per fixed one-hour window. A new code replaces the previous code. Database state contains a keyed HMAC of the code, never its plaintext. The HMAC secret is separate from the database and Resend API key.

`POST /auth/password-reset/request` accepts `email` and returns HTTP 202 with the same message for registered, unregistered, ambiguous, and throttled accounts. It does not claim delivery succeeded. Email is sent in a background task after the response. Provider/database errors are logged with a generic message that excludes secrets and addresses. Background delivery is not a durable queue: if a process stops or delivery fails, users must request another code after the cooldown; failed delivery still counts toward the quota.

`POST /auth/password-reset/confirm` accepts `email`, `code`, and `new_password`. A successful transaction replaces the bcrypt password hash, consumes the code, clears login lockout, and revokes every session for that user. It does not automatically log the user in. Authenticated password changes also invalidate outstanding recovery codes. Send quotas survive code consumption. Legacy duplicate email addresses cannot be used to reset an arbitrarily chosen account.

Password input preserves spaces and follows the existing nonempty-password policy, with a 72 UTF-8 byte maximum and no null character to prevent bcrypt truncation/errors. This does not introduce a new password-strength policy for the project.

## Server setup before deployment

1. Create and download a fresh database backup under a new filename, retaining earlier backups.
2. Apply **only** `db/migrate_password_recovery.sql` in Beekeeper against `infox_db`. Previous session and login-lockout migrations must already be applied. Verify with `SHOW CREATE TABLE infox_db.password_reset_state;`. The full schema is for fresh installations.
3. Add the settings from `.env.password-recovery.example` to the server's existing private `.env`, preserving DB and other settings:

   ```dotenv
   RESEND_API_KEY=your-private-resend-api-key
   RESEND_FROM_EMAIL="InfoX <noreply@mail.projectinfox.tech>"
   PASSWORD_RESET_SECRET=your-new-random-secret
   ```

   Generate the reset secret privately on the server with `openssl rand -hex 32`. Copy the generated value into `.env`; do not paste it into chat or a commit. Keep the same secret across Uvicorn workers and restarts. Rotating it invalidates outstanding reset codes. The example values above are placeholders and must not be used as real secrets.

4. Ensure `mail.projectinfox.tech` is verified for sending in Resend and the API key has sending permission for that domain. The sender is `InfoX <noreply@mail.projectinfox.tech>`. The server must reach `https://api.resend.com` over HTTPS. This implementation uses Python's standard HTTP library, so no new package installation is required. API contract: [Resend Send Email](https://resend.com/docs/api-reference/emails/send-email).
5. Commit and push the backend feature through your account, then confirm your cron job deployed that commit and restarted Uvicorn. Suggested branch: `codex/password-recovery`, created from the current feature branch so previous changes are retained.
6. Install the updated APK and run the device checks in the app's `PASSWORD_RECOVERY.md` before committing the frontend.

Missing settings return a generic HTTP 503 for all accounts. An accepted request with no email can mean unknown/duplicate email, a resend limit, background interruption, or delivery failure. Check the generic backend error and Resend dashboard privately. Do not post API keys, reset codes, full `.env`, or provider payloads into shared logs. Existing login/session operations do not require Resend configuration, but authenticated password changes require the migration because they invalidate reset state.

## Validation

All 23 backend tests passed with:

```text
python -m unittest tests.test_registration_validation tests.test_auth_sessions tests.test_password_recovery -v
```

Tests cover generic responses, hashed code storage, wrong codes, expiry, single use, resend replacement/cooldown/quota, cross-account rejection, session revocation, lockout clearing, password-change invalidation, invalid inputs, duplicate email handling, provider failure, the Resend HTTP request contract, and transaction rollback. They use isolated SQLite and mocked email; they do not verify real delivery, deployed MySQL syntax/locking, or concurrent workers. Those checks remain pending.

## Backend commit

Title: `feat(auth): add single-use email password recovery with Resend`

Body:

- Add generic reset-code requests and atomic password-reset confirmation endpoints.
- Deliver eight-digit codes through Resend using backend-only configuration and bounded HTTP calls.
- Store keyed code hashes with ten-minute expiry, five verification attempts, and per-account resend limits.
- Replace old codes on resend and invalidate recovery codes after successful reset or authenticated password change.
- Revoke all sessions and clear login lockout after a verified reset while retaining email-send quotas.
- Reject ambiguous duplicate emails and passwords that exceed bcrypt's byte limit.
- Add an incremental migration, fresh-install schema, and a secrets-free configuration template.
- Validate authentication and recovery with 23 passing isolated backend tests; real delivery and deployed MySQL checks remain pending.

Include exactly:

- `.env.password-recovery.example`
- `db/schema.sql`
- `db/migrate_password_recovery.sql`
- `routers/auth.py`
- `schemas.py`
- `services/password_recovery.py`
- `tests/test_auth_sessions.py`
- `tests/test_password_recovery.py`
- `PASSWORD_RECOVERY.md`

Exclude the real `.env`, database backups, and unrelated existing guides/dataset scripts. The assistant has not staged, committed, pushed, migrated, configured, or deployed these changes, and has sent no real email.
