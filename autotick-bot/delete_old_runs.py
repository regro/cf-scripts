import github
import os
import sys
import requests
import datetime
import time

gh = github.Github(os.environ["GITHUB_TOKEN"])
r = gh.get_repo("regro/cf-scripts")
done = 0
for w in r.get_workflows():
    for rn in w.get_runs().reversed:
        if rn.status == "completed" and (
            datetime.datetime.utcnow() - rn.updated_at > datetime.timedelta(days=90)
        ):
            requests.delete(
                rn.url,
                headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"]},
            )
            done += 1
            time.sleep(1)
        if done == 1000:
            sys.exit(0)
