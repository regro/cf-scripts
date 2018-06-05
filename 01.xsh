#!/usr/bin/env xonsh
import time

$XONSH_SHOW_TRACEBACK = True

ls -lart

source bot.xsh

cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

xonsh ../cf-scripts/03-auto_tick.xsh
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .

times = [time.time()]
conda-forge-tick --run 0
times.append(time.time())
conda-forge-tick --run 1
times.append(time.time())
conda-forge-tick --run 2
times.append(time.time())

for i in range(len(times) - 1):
    print('BOT TIME stage {}: {}'.format(i, times[i+1] - times[i]))

doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
xonsh ../cf-scripts/03-auto_tick.xsh
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
