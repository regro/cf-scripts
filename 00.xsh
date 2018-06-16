#!/usr/bin/env xonsh
import time
cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

start = time.time()
xonsh ../cf-scripts/03-auto_tick.xsh
print('FINISHED STAGE 3 IN {} SECONDS'.format(i, time.time() - start))
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .

start = time.time()
for i in range(3):
    conda-forge-tick --run @(i)
    print('FINISHED STAGE {} IN {} SECONDS'.format(i, time.time() - start))
    start = time.time()
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .

start = time.time()
xonsh ../cf-scripts/03-auto_tick.xsh
print('FINISHED STAGE 3 IN {} SECONDS'.format(i, time.time() - start))
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
