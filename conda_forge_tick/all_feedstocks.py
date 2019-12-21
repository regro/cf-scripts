import datetime
import os
import github3
import logging

from .utils import setup_logger

logger = logging.getLogger("conda_forge_tick.all-feedstocks")


def get_all_feedstocks_from_github():
    gh = github3.login(os.environ["USERNAME"], os.environ["PASSWORD"])
    org = gh.organization("conda-forge")
    names = []
    try:
        for repo in org.repositories():
            name = repo.name
            if name.endswith("-feedstock"):
                name = name.split("-feedstock")[0]
                logger.info(name)
                names.append(name)
    except github3.GitHubError as e:
        msg = ["Github rate limited. "]
        c = gh.rate_limit()["resources"]["core"]
        if c["remaining"] == 0:
            ts = c["reset"]
            msg.append("API timeout, API returns at")
            msg.append(
                datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        logger.warning(" ".join(msg))
        raise
    return names


def get_all_feedstocks(cached=False):
    if cached:
        logger.info("reading names")
        with open("names.txt", "r") as f:
            names = f.read().split()
        return names

    names = get_all_feedstocks_from_github()
    return names


def main(args=None):
    setup_logger(logger)
    names = get_all_feedstocks(cached=False)
    with open("names.txt", "w") as f:
        for name in names:
            f.write(name)
            f.write("\n")


if __name__ == "__main__":
    main()
