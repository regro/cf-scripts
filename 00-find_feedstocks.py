import datetime
import os

import github3
import networkx as nx

gh = github3.login(os.environ['USERNAME'], os.environ['PASSWORD'])
org = gh.organization('conda-forge')
with open('names.txt', 'w') as f:
    try:
        for repo in org.iter_repos():
            name = repo.full_name.split('conda-forge/')[-1]
            if 'feedstock' in name and 'feedstocks' not in name:
                print(name.split('-feedstock')[0])
                f.write(name.split('-feedstock')[0])
                f.write('\n')
    except github3.GitHubError as e:
        print(e)
        c = gh.rate_limit()['resources']['core']
        if c['remaining'] == 0:
            ts = c['reset']
            print('API timeout, API returns at')
            print(datetime.datetime.utcfromtimestamp(ts)
                  .strftime('%Y-%m-%dT%H:%M:%SZ'))
        pass

gx = nx.read_gpickle('graph.pkl')
nx.write_yaml(gx, 'graph.yml')
