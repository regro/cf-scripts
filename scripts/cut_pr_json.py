import glob
import tqdm

from conda_forge_tick.lazy_json_backends import load, dump
from conda_forge_tick.git_utils import trim_pr_josn_keys


fnames = glob.glob("pr_json/*.json")
print("found %d json files" % len(fnames), flush=True)

for fname in tqdm.tqdm(fnames):
    with open(fname) as fp:
        pr_json = load(fp)
    pr_json = trim_pr_josn_keys(pr_json)
    with open(fname, "w") as fp:
        dump(pr_json, fp)
