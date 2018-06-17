#!/usr/bin/env xonsh
import time
cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

stage = 1
start = time.time()
conda-forge-tick --run @(stage)
print('FINISHED STAGE {} IN {} SECONDS'.format(stage, time.time() - start))
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
