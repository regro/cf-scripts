# cf-scripts
Conda-Forge dependency graph tracker and auto ticker

[regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+) 

## Plan
There are four scripts:
1. `00-find-feedstocks.py` which finds all the names of the current feedstocks. (#feedstocks/30 GH api calls)
1. `01-make_graph.py` which makes the DAG of packages and their dependencies using `networkx` with each recipe represented by a node. Important data from the `meta.yaml` for each recipe stuffed into the node `attrs`. (single GH api call per feedstock)
1. `02-graph-upstream.py` finds versions for each recipe's upstream source. (potential 2 GH calls per feedstock (if on GH))
1. `03-auto_tick.xsh` takes each node which is out of date and creates a PR to bring the recipe up to date with the source. This requires `xonsh` and will skip CI for packages who's dependencies are also out of date. (multiple GH api calls)

These scripts will run on Travis from 4 different github repos as daily cron jobs and use `doctr` to write the output data (the list of all conda-forge packages and the dependency graph) to this repo. 

GH rate limit is a major concern for this as there are ~4000 feedstocks and only 5000 API calls per hour.
