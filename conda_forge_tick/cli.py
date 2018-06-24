import argparse
from .all_feedstocks import main as main0
from .make_graph import main as main1
from .update_upstream_versions import main as main2
from .auto_tick import main as main3


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("--run")
    args = parser.parse_args()
    script = int(args.run)
    if script == 0:
        main0()
    elif script == 1:
        main1()
    elif script == 2:
        main2()
    elif script == 3:
        main3()
    else:
        raise RuntimeError("Unknown script number")
