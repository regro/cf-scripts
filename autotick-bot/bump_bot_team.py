import os
import sys
import github


if os.environ["ACTION_NAME"] == "bot":
    gh = github.Github(os.environ["PASSWORD"])

    repo = gh.get_repo("regro/autotick-bot")

    repo.create_issue(
        title="failed job %s" % os.environ["ACTION_NAME"],
        body="""
Hey @regro/auto-tick-triage!

It appears that the bot `%s` job failed! :(

I hope it is not too much work to fix but we all know that is never the case.

Have a great day!

job url: %s

"""
        % (os.environ["ACTION_NAME"], os.environ["ACTION_URL"]),
    )

sys.exit(1)
