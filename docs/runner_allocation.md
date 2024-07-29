# GitHub Runner Allocation

Last Updated: 2024-07-29

We have a
[concurrency of 20 runners available](https://docs.github.com/en/actions/administering-github-actions/usage-limits-billing-and-administration#usage-limits) in the entire `regro` account.

These are split across our workflows as follows:
- `bot-bot` - 1 runner
- `bot-cache` - currently disabled
- `bot-feedstocks` (daily for ~30 minutes) - 1 runner
- `bot-make-graph` - 3 runners
- `bot-make-migrators` - 1 runner
- `bot-prs` - 4 runners
- `bot-pypi-mapping` (hourly for ~5 minutes) - 1 runner
- `bot-update-status-page` - 1 runner
- `bot-versions` - 6 runners
- `docker` (on demand) - 1 runner
- `keepalive` (hourly for ~5 minutes) - 1 runner
- `relock` (every 3 hours for ~1 minute) - 1 runner
- `test-model` (daily for ~4 minutes, on demand) - 1 runner
- `tests` (on demand) - 1 runner

Total: 16 runners used permanently, 4 runners can be used on demand.
