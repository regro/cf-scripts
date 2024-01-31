from typing import Any, List

import tqdm
import github
import logging

from conda_forge_tick import sensitive_env
from .cli_context import CliContext
from .utils import setup_logger
from .lazy_json_backends import load, dump

logger = logging.getLogger("conda_forge_tick.all_feedstocks")


def get_all_feedstocks_from_github():
    with sensitive_env() as env:
        gh = github.Github(env["PASSWORD"], per_page=100)

    org = gh.get_organization("conda-forge")
    archived = set()
    not_archived = set()
    default_branches = {}
    repos = org.get_repos(type="public")
    for r in tqdm.tqdm(
        repos,
        total=org.public_repos,
        desc="getting all feedstocks",
        ncols=80,
    ):
        if r.name.endswith("-feedstock"):
            name = r.name

            if r.archived:
                archived.add(name[: -len("-feedstock")])
            else:
                not_archived.add(name[: -len("-feedstock")])

            default_branches[name[: -len("-feedstock")]] = r.default_branch

    return {
        "active": sorted(list(not_archived)),
        "archived": sorted(list(archived)),
        "default_branches": default_branches,
    }


def get_all_feedstocks(cached: bool = False) -> List[str]:
    if cached:
        logger.info("reading cached feedstocks")
        with open("all_feedstocks.json") as f:
            names = load(f)["active"]
    else:
        logger.info("getting feedstocks from github")
        names = get_all_feedstocks_from_github()["active"]
    return names


def get_archived_feedstocks(cached: bool = False) -> List[str]:
    if cached:
        logger.info("reading cached archived feedstocks")
        with open("all_feedstocks.json") as f:
            names = load(f)["archived"]
    else:
        logger.info("getting archived feedstocks from github")
        names = get_all_feedstocks_from_github()["archived"]
    return names


def main(ctx: CliContext) -> None:
    if ctx.debug:
        setup_logger(logger, level="debug")
    else:
        setup_logger(logger)
    logger.info("fetching active feedstocks from github")
    data = get_all_feedstocks_from_github()
    with open("all_feedstocks.json", "w") as fp:
        dump(data, fp)
