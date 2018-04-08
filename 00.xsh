$START_TIME = int("$(date +%s)")
$TIMEOUT = 2700
sh setup.sh
cd ../cf-graph
$PATH.insert(0, '~/mc/bin')
conda-forge-tick --run 0
conda-forge-tick --run 1
conda-forge-tick --run 2
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
xonsh ../cf-scripts/03-auto_tick.xsh
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .