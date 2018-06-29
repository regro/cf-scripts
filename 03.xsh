#!/usr/bin/env xonsh
import os
import time
from rever.tools import indir

cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

stages = [3]
start = time.time()
for i in stages:
    conda-forge-tick --run @(i)
    print('FINISHED STAGE {} IN {} SECONDS'.format(i, time.time() - start))
    start = time.time()
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
pwd
du -hs * | sort -hr
print('/tmp/*')
du -h /tmp/* | sort -hr
