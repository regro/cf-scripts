import networkx as nx
import github3
import os


def main():
    gh = github3.login(os.environ["USERNAME"], os.environ["PASSWORD"])

    gx = nx.read_gpickle('graph.pkl')

    gh_name = os.environ["USERNAME"]

    subs = {v.name: v for v in gh.subscriptions()}

    for node, attrs in gx.node.items():
        # if currently subscribed and not a maintainer
        if (node in subs and
                gh_name not in attrs['meta_yaml']['extra']['recipe-maintainers']):
            print('unsubscribing from {}'.format(node))
            # not certain this will work (seems like a bug in github3)

            # subs[node].subscribe(False, False)
