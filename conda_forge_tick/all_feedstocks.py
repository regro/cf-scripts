import logging
from typing import List

import tqdm

from conda_forge_tick.git_utils import github_client

from .lazy_json_backends import dump, load
from .settings import settings

logger = logging.getLogger(__name__)


def get_all_feedstocks_from_github():
    gh = github_client()
    org = gh.get_organization(settings().conda_forge_org)
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


def main() -> None:
    logger.info("fetching active feedstocks from github")
    data = get_all_feedstocks_from_github()
    with open("all_feedstocks.json", "w") as fp:
        dump(data, fp)
