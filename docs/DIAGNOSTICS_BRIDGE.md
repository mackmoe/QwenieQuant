# Optional private GitHub diagnostics bridge

This opt-in sidecar publishes a strictly allowlisted, read-only JSON health
snapshot every 15 minutes to a SEPARATE PRIVATE GitHub repository. It is not
a Discord connector or an SSH tunnel; no Discord message history is copied.
It calls existing internal HTTP health and queue/activity GET endpoints only.
It has no database credentials, Kalshi credentials, host port, Docker socket,
or order-placement capabilities.

IMPORTANT: QwenieQuant itself is PUBLIC. Do not publish a diagnostic report
to the source repository. The bridge refuses to upload unless the destination
GitHub API verifies the repository is private. Snapshots remain in the private
destination repo's Git history even when latest.json is overwritten.

## First-time setup (on your server)

1. Create a NEW PRIVATE GitHub repository such as
   YOUR_USER/qweniequant-diagnostics. Grant the ChatGPT GitHub integration
   access to this new repo if you want the assistant to inspect the reports.
2. Generate a fine-grained GitHub token restricted to that PRIVATE diagnostics
   repo only, with Contents read/write permission (Metadata read is implicit).
   Do not grant broad all-repository or administration permissions.
3. Create a file containing only that token, on the server, at:
   compose/keys/diagnostics_github_token
   The compose/keys directory is gitignored. Protect the file with
   chmod 600 compose/keys/diagnostics_github_token
   Never paste the token into ChatGPT or Discord, or commit it to Git.
4. In your server's compose/.env, set:
   DIAG_PRIVATE_REPO=YOUR_USER/qweniequant-diagnostics
5. From the repository root start only the optional reporter:

   docker compose --env-file compose/.env -f compose/docker-compose.yml --profile diagnostics up -d diagnostics-bridge

6. Review its logs:

   docker compose --env-file compose/.env -f compose/docker-compose.yml logs --tail=25 diagnostics-bridge

   A successful cycle logs the number of healthy endpoints, never secrets.
   The report appears in the private destination at
   reports/qweniequant/latest.json on its default branch.

Stop collection at any time:

   docker compose --env-file compose/.env -f compose/docker-compose.yml --profile diagnostics stop diagnostics-bridge

Then optionally revoke the fine-grained token.

## What gets reported

- UTC timestamp and per-service health booleans.
- Queue size/state COUNTS (not queue entries, titles, market tickers).
- Last-hour processed, approved, and would-approve counts; directional count;
  reported mean CLAIMED GROSS edge and queue aging.
- The risk manager's dry-run setting, PostgreSQL health, and Kalshi API
  connectivity, credentials-present boolean and production/demo indicator.
- Market scan and tier-3 candidate COUNTS.

Missing values are null, not made-up zeros. This bridge never exports raw
logs, error strings, market IDs, predictions, reasoning, balances, trade IDs,
Discord messages, credentials, full HTTP responses, or stack traces.

## Limitations and security

The reported mean edge is gross model CLAIMED edge, not net trading profit.
This snapshot does not verify actual fills, paid fees, or settled gains.
Those require separate, explicitly authorized analysis of transaction records.

- This service is disabled unless explicitly started via the optional
  Compose diagnostics profile; existing trading behavior is unchanged.
- The GitHub API must be reachable over HTTPS; NO inbound port forwarding is
  needed.
- An expired/revoked token results in a generic error log and retry on the
  next 15-minute cycle.
- The new private repo needs to be connected to ChatGPT separately. GitHub
  authorization for the public source repository does not automatically
  grant access to the private diagnostics destination.
- Run isolated tests with:
  python -m unittest discover -s services/diagnostics-bridge/tests -v
