import os
import sys
import textwrap
from datetime import datetime

import github

today = datetime.today().strftime("%Y-%m-%d")
issue_title = f"[{today}] failed job {os.environ['ACTION_NAME']}"

gh = github.Github(os.environ["BOT_TOKEN"])
repo = gh.get_repo("regro/cf-scripts")

# find any issues from today, if any
max_try = 50
issue = None
tried = 0
for _issue in repo.get_issues():
    tried += 1
    if _issue.title == issue_title:
        issue = _issue
        break
    if tried > max_try:
        break

if issue is None:
    body = (
        textwrap.dedent(
            """\
        Hey @regro/auto-tick-triage!

        It appears that the bot `%s` job(s) below failed! :(

        """
        )
        % os.environ["ACTION_NAME"]
    )
    issue = repo.create_issue(
        title=issue_title,
        body=body,
    )
else:
    body = issue.body

new_body = body + (
    f"""\
- [ ] {os.environ["ACTION_URL"]}
"""
)

issue.edit(body=new_body)

sys.exit(1)
