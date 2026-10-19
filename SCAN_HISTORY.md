# Authenticated scan history deployment

Adds `GET /scans?limit=20&before=<scan_id>`, returning `scans` and `next_before`.
Authentication uses the existing bearer session. The database query scopes rows to
that session's user ID; a supplied user_id query parameter cannot select another
account. Results contain scan ID, status, translated text and creation date, never
server image paths. The endpoint is read-only and uses the existing scans table.
No database migration or environment-variable change is required.

Commit and merge this backend change before device-testing the new Flutter history
screen. Your existing cron deployment can pull it and restart Uvicorn. Verify that
Past scans loads after deployment. Local saves do not depend on this endpoint.

Suggested branch: `codex/scan-history`.
Include only:

- `main.py`
- `routers/history.py`
- `tests/test_scan_history.py`
- `SCAN_HISTORY.md`

Do not include other existing untracked guides/scripts. The local venv is ignored.
No commits or pushes were performed by the agent.

Title:

```text
feat(history): expose paginated scans for the authenticated user
```

Description:

```text
Add a read-only GET /scans endpoint backed by the existing scans table. Derive
ownership from the authenticated session, return newest scans first, and paginate
using a bounded limit and scan-ID cursor.

Return status, translated text and creation date so the mobile app can reopen
completed translations and distinguish pending or failed scans. Keep server file
paths out of the response and preserve all server records when users delete local
saved copies.

Register the router and test authentication, cross-account isolation, cursor
pagination, empty results and query validation using a temporary SQLite database.
No production database is touched by these tests and no schema migration is needed.
```

Validation: three history endpoint tests and eleven existing session/authentication
integration tests passed locally. SQLite tests do not replace live MySQL deployment
verification. Device-test instructions are in frontend LOCAL_SAVES_HISTORY.md.
