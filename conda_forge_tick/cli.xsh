import argparse
import time
import os

from doctr.travis import run_command_hiding_token as doctr_run

from .utils import load_graph, LazyJson

from .all_feedstocks import main as main_all_feedstocks
from .make_graph import main as main_make_graph
from .update_upstream_versions import main as main_update_upstream_versions
from .auto_tick import main as main_auto_tick
from .status_report import main as main_status_report
from .audit import main as main_audit
from .update_prs import main as main_update_prs


def deploy(args):
    """Deploy the graph to github"""
    if args.dry_run:
        print("(dry run) deploying")
        return
    for cmd in [['git', 'pull', '-s', 'recursive', '-X', 'theirs'],
                ['git', 'add', 'pr_json/*'],
                ['git', 'add', 'status/*'],
                ['git', 'add', 'node_attrs/*'],
                ['git', 'add', 'audits/*'],
                ['git', 'commit', '-am', f'"Update Graph {$CIRCLE_BUILD_URL}"']]:
        try:
            @(cmd)
        except Exception as e:
            print(e)

    try:
        gx = load_graph()
        # TODO: be more selective about which json to check
        for node, attrs in gx.nodes.items():
            attrs["payload"]._load()
        graph_ok = True
    except Exception:
        graph_ok = False

    status = 1
    num_try = 0
    while status != 0 and num_try < 10 and graph_ok:
        try:
            if num_try == 9:
                @(["git", "fetch", "--unshallow"])
            @(['git', 'pull', '-s', 'recursive', '-X', 'theirs'])
        except Exception:
            pass
        status = doctr_run(
            ['git',
             'push',
             'https://{token}@github.com/{deploy_repo}.git'.format(
                 token=$PASSWORD, deploy_repo='regro/cf-graph-countyfair'),
             'master'],
             token =$PASSWORD.encode('utf-8'))

        num_try += 1

    if status != 0 or not graph_ok:
        if not graph_ok:
            @(["git", "fetch", "--unshallow"])
        _branch = "failed-circle-run-%s" % os.environ["CIRCLE_BUILD_NUM"]
        @(["git", "checkout", "-b", _branch])
        @(["git", "commit", "--allow-empty", "-am", '"help me @regro/auto-tick!"'])

        status = doctr_run(
            ['git',
             'push',
             '--set-upstream',
             'https://{token}@github.com/{deploy_repo}.git'.format(
                 token=$PASSWORD, deploy_repo='regro/cf-graph-countyfair'),
             _branch],
             token =$PASSWORD.encode('utf-8'))

        raise RuntimeError("bot did not push its data! stopping!")



int_script_dict = {
  0: main_all_feedstocks,
  1: main_make_graph,
  2: main_update_upstream_versions,
  3: main_auto_tick,
  4: main_status_report,
  5: main_audit,
  6: main_update_prs,
  -1: deploy
}


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("--run")
    parser.add_argument("--debug", dest="debug", action="store_true", default=False,
        help="Runs in debug mode, running parallel parts sequentially and printing more info.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False,
                        help="Don't push changes to PRs or graph to Github")
    args = parser.parse_args()
    $CONDA_FORGE_TICK_DEBUG = args.debug
    script = int(args.run)
    if script in int_script_dict:
        start = time.time()
        int_script_dict[script](args)
        print('FINISHED STAGE {} IN {} SECONDS'.format(script, time.time() - start))
    else:
        raise RuntimeError("Unknown script number")
