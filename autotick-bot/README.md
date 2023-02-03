# autotick-bot
[![update-status-page](https://github.com/regro/autotick-bot/workflows/update-status-page/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Aupdate-status-page)
[![pypi-mapping](https://github.com/regro/autotick-bot/workflows/pypi-mapping/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Apypi-mapping)
[![versions](https://github.com/regro/autotick-bot/workflows/versions/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Aversions)
[![prs](https://github.com/regro/autotick-bot/workflows/prs/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Aprs)
[![bot](https://github.com/regro/autotick-bot/workflows/bot/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Abot)
[![feedstocks](https://github.com/regro/autotick-bot/workflows/feedstocks/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Afeedstocks)
[![delete-old-runs](https://github.com/regro/autotick-bot/actions/workflows/delete-old-runs.yml/badge.svg)](https://github.com/regro/autotick-bot/actions/workflows/delete-old-runs.yml)

the actual bot in an actual place doing an actual thing

## Starting and Stopping the Worker

In order to start the worker, make a commit to master with the file `please.go`
in the top-level directory.

If you want to stop the worker, simply delete this file and it will not restart
itself on the next round. When stopping the worker, make sure to add `ci skip` to the commit message. 

## What has the bot done recently?

Check out its [PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+), its currently [running jobs](https://github.com/regro/autotick-bot/actions?query=is%3Ain_progress++), and the [status page](https://conda-forge.org/status/#current_migrations)!
