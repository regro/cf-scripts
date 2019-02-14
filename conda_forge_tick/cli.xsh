import argparse
import time

from doctr.travis import run_command_hiding_token as doctr_run

from .all_feedstocks import main as main_all_feedstocks
from .make_graph import main as main_make_graph
from .update_upstream_versions import main as main_update_upstream_versions
from .auto_tick import main as main_auto_tick
from .status_report import main as main_status_report


def deploy():
    """Deploy the graph to github"""
    for cmd in [['git', 'add', 'pr_json/*'],
                ['git', 'add', 'status/*'],
                ['git', 'commit', '-am', '"Update Graph"']]:
        try:
            @(cmd)
        except Exception as e:
            print(e)
    doctr_run(
        ['git',
         'push',
         'https://{token}@github.com/{deploy_repo}.git'.format(
             token=$PASSWORD, deploy_repo='regro/cf-graph3'),
         'master'],
         token =$PASSWORD.encode('utf-8'))


int_script_dict = {
  0: main_all_feedstocks,
  1: main_make_graph,
  2: main_update_upstream_versions,
  3: main_auto_tick,
  4: main_status_report,
  -1: deploy
}


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("--run")
    parser.add_argument("--debug", dest="debug", action="store_true", default=False,
        help="Runs in debug mode, running paraellel parts sequentially and printing more info.")
    args = parser.parse_args()
    $CONDA_FORGE_TICK_DEBUG = args.debug
    script = int(args.run)
    if script in int_script_dict:
        start = time.time()
        int_script_dict[script]()
        print('FINISHED STAGE {} IN {} SECONDS'.format(script, time.time() - start))
    else:
        raise RuntimeError("Unknown script number")
