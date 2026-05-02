import os
import sys

import github

tag = sys.argv[1]
gh = github.Github(auth=github.Auth.Token(os.environ["GITHUB_TOKEN"]))
repo = gh.get_repo("regro/cf-scripts")

repo.create_git_release(
    tag=tag,
    name=tag,
    draft=False,
    prerelease=False,
    generate_release_notes=True,
)
