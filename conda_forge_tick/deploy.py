import os
import subprocess

from doctr.travis import run_command_hiding_token as doctr_run

from . import sensitive_env
from .cli_context import CliContext
from .lazy_json_backends import CF_TICK_GRAPH_DATA_HASHMAPS, get_lazy_json_backends
from .utils import load_existing_graph

BUILD_URL_KEY = "CIRCLE_BUILD_URL"


def _run_git_cmd(cmd):
    return subprocess.run(cmd, shell=True, check=True)


def deploy(ctx: CliContext, dirs_to_deploy: list[str] = None):
    """Deploy the graph to GitHub"""
    if ctx.dry_run:
        print("(dry run) deploying")
        return

    # TODO: have function construct this
    BUILD_URL = os.environ.get(BUILD_URL_KEY, "")

    # pull changes, add ours, make a commit
    try:
        _run_git_cmd("git pull -s recursive -X theirs")
    except Exception as e:
        print(e)

    files_to_add = set()
    if dirs_to_deploy is None:
        drs_to_deploy = [
            "status",
            "mappings",
            "mappings/pypi",
            "ranked_hubs_authorities.json",
            "all_feedstocks.json",
            "import_to_pkg_maps",
        ]
        if "file" in get_lazy_json_backends():
            drs_to_deploy += CF_TICK_GRAPH_DATA_HASHMAPS
            drs_to_deploy += ["graph.json"]
    else:
        drs_to_deploy = dirs_to_deploy

    for dr in drs_to_deploy:
        # untracked
        files_to_add |= set(
            subprocess.run(
                f"git ls-files -o --exclude-standard {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

        # changed
        files_to_add |= set(
            subprocess.run(
                f"git diff --name-only {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

        # modified and staged but not deleted
        files_to_add |= set(
            subprocess.run(
                f"git diff --name-only --cached --diff-filter=d {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

    print("found %d files to add" % len(files_to_add), flush=True)

    n_added = 0
    max_per_batch = 500
    batch = 0
    while files_to_add:
        batch += 1
        n_added_this_batch = 0
        while files_to_add and n_added_this_batch < max_per_batch:
            file = files_to_add.pop()
            if file and os.path.exists(file):
                try:
                    print(f"committing {n_added: >5d}: {file}", flush=True)
                    _run_git_cmd(f"git add {file}")
                    n_added_this_batch += 1
                    n_added += 1
                except Exception as e:
                    print(e)

        if n_added_this_batch > 0:
            try:
                _step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
                _run_git_cmd(f'git commit -am "{_step_name} {batch: >3d} - {BUILD_URL}"')
            except Exception as e:
                print(e)

            # make sure the graph can load, if not we will error
            try:
                gx = load_existing_graph()
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
                        print(
                            "\n\n>>>>>>>>>>>> git unshallow for try %d\n\n" % num_try,
                            flush=True,
                        )
                        _run_git_cmd("git fetch --unshallow")
                    print("\n\n>>>>>>>>>>>> git pull try %d\n\n" % num_try, flush=True)
                    _run_git_cmd("git pull -s recursive -X theirs")
                except Exception as e:
                    print(
                        "\n\n>>>>>>>>>>>> git pull try %d failed: %s \n\n" % (num_try, e),
                        flush=True,
                    )
                    pass
                print("\n\n>>>>>>>>>>>> git push try %d\n\n" % num_try, flush=True)
                with sensitive_env() as env:
                    status = doctr_run(
                        [
                            "git",
                            "push",
                            "https://{token}@github.com/{deploy_repo}.git".format(
                                token=env.get("PASSWORD", ""),
                                deploy_repo="regro/cf-graph-countyfair",
                            ),
                            "master",
                        ],
                        token=env.get("PASSWORD", "").encode("utf-8"),
                    )
                num_try += 1

            if status != 0 or not graph_ok:
                # this never works so we'll just stop
                # print("\n\n>>>>>>>>>>>> failed deploy - pushing to branch\n\n", flush=True)
                # if not graph_ok:
                #     print("\n\n>>>>>>>>>>>> git unshallow graph bad\n\n", flush=True)
                #     _run_git_cmd("git fetch --unshallow")
                # _branch = "failed-circle-run-%s" % os.environ["CIRCLE_BUILD_NUM"]
                # _run_git_cmd(f"git checkout -b {_branch}")
                # _run_git_cmd("git commit --allow-empty -am 'help me!'")

                # with sensitive_env() as env:
                #     status = doctr_run(
                #         [
                #             "git",
                #             "push",
                #             "--set-upstream",
                #             "https://{token}@github.com/{deploy_repo}.git".format(
                #                 token=env.get("PASSWORD", ""),
                #                 deploy_repo="regro/cf-graph-countyfair",
                #             ),
                #             _branch,
                #         ],
                #         token=env.get("PASSWORD", "").encode("utf-8"),
                #     )

                raise RuntimeError("bot did not push its data! stopping!")
