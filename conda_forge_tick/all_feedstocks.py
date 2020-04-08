from typing import Any, List

import requests
import logging

from .utils import setup_logger

logger = logging.getLogger("conda_forge_tick.all-feedstocks")


def get_all_feedstocks_from_github() -> List[str]:
    r = requests.get(
        "https://raw.githubusercontent.com/conda-forge/admin-migrations/"
        "master/data/all_feedstocks.json"
    )
    if r.status_code != 200:
        raise RuntimeError("could not get feedstocks!")

    return r.json()["arctive"]


def get_all_feedstocks(cached: bool = False) -> List[str]:
    if cached:
        logger.info("reading names")
        with open("names.txt", "r") as f:
            names = f.read().split()
        return names

    names = get_all_feedstocks_from_github()
    return names


def main(args: Any = None) -> None:
    setup_logger(logger)
    names = get_all_feedstocks(cached=False)
    with open("names.txt", "w") as f:
        for name in names:
            f.write(name)
            f.write("\n")


if __name__ == "__main__":
    main()
