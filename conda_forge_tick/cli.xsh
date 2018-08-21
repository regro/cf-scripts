import argparse
import time

from doctr.travis import run_command_hiding_token as doctr_run

from .all_feedstocks import main as main0
from .make_graph import main as main1
from .update_upstream_versions import main as main2
from .auto_tick import main as main3


def deploy():
    """Deploy the graph to github"""
    try:
        git commit -am Update Graph
    except Exception as e:
        print(e)
    doctr_run(
        ['git',
         'push',
         'https://{token}@github.com/{deploy_repo}.git'.format(
             token=$PASSWORD, deploy_repo='regro/cf-graph'),
         'master'],
         token =$PASSWORD.encode('utf-8'))


int_script_dict = {0: main0, 1: main1, 2: main2, 3: main3, -1: deploy}


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("--run")
    args = parser.parse_args()
    script = int(args.run)
    if script in int_script_dict:
        start = time.time()
        int_script_dict[script]()
        print('FINISHED STAGE {} IN {} SECONDS'.format(script, time.time() - start))
    else:
        raise RuntimeError("Unknown script number")
