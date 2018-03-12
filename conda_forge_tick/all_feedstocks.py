import datetime
import os
import github3
import logging

logger = logging.getLogger("conda_forge_tick.all-feedstocks")

def get_all_feedstocks_from_github():
    gh = github3.login(os.environ['USERNAME'], os.environ['PASSWORD'])
    org = gh.organization('conda-forge')
    names = []
    try:
        for repo in org.iter_repos():
            name = repo.full_name.split('conda-forge/')[-1]
            if name.endswith('-feedstock'):
                name = name.split('-feedstock')[0]
                logger.info(name)
                names.append(name)
    except github3.GitHubError as e:
        msg = ["Github rate limited. "]
        c = gh.rate_limit()['resources']['core']
        if c['remaining'] == 0:
            ts = c['reset']
            msg.append('API timeout, API returns at')
            msg.append(datetime.datetime.utcfromtimestamp(ts)
                  .strftime('%Y-%m-%dT%H:%M:%SZ'))
        logger.warn(" ".join(msg))
        raise e
    return names


def get_all_feedstocks(cached=False):
    if cached:
        logger.info('reading names')
        with open('names.txt', 'r') as f:
            names = f.read().split()
        return names

    names = get_all_feedstocks_from_github()
    with open('names.txt', 'w') as f:
        for name in names:
            f.write(name)
            f.write('\n')

def main(*args, **kwargs):
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.INFO)
    get_all_feedstocks(cached=False)

if __name__ == "__main__":
    main()
