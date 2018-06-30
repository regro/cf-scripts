#!/usr/bin/env xonsh
import os
import time
from rever.tools import indir
from doctr.travis import run_command_hiding_token as doctr_run

cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

stages = [3]
start = time.time()
for i in stages:
    conda-forge-tick --run @(i)
    print('FINISHED STAGE {} IN {} SECONDS'.format(i, time.time() - start))
    start = time.time()
doctr_run(
    ['git',
     'push',
     'https://{token}@github.com/{deploy_repo}.git'.format(
         token=$PASSWORD, deploy_repo='regro/cf-graph'),
     'master'],
     token=$PASSWORD)
pwd
du -hs * | sort -hr
print('/tmp/*')
du -h /tmp/* | sort -hr
