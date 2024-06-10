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
    if issue.title == issue_title:
        issue = _issue
        break
    if tried > max_try:
        break

if issue is None:
    issue = repo.create_issue(
        title=issue_title,
        body=textwrap.dedent(
            """\
            Hey @regro/auto-tick-triage!

            It appears that the bot `%s` job failed! :(

            I hope it is not too much work to fix but we all know that is never the case.

            Have a great day!
            """
        )
        % os.environ["ACTION_NAME"],
    )

issue.create_comment(
    textwrap.dedent(
        """\
        Hey @regro/auto-tick-triage!

        There is (possibly another) failure of this bot job! :(

        Check the logs for more details: %s
        """
        % os.environ["ACTION_URL"]
    )
)

sys.exit(1)
