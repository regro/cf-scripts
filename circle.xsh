#!/usr/bin/env xonsh
import os
import time
from rever.tools import indir
from doctr.travis import run_command_hiding_token as doctr_run

cd ../cf-graph
$PATH.insert(0, '~/mc/bin')

stages = [0, 1, 2, 3]
start = time.time()
for i in stages:
    conda-forge-tick --run @(i)
    print('FINISHED STAGE {} IN {} SECONDS'.format(i, time.time() - start))
    start = time.time()
    try:
        git commit -am @("Finished stage {}".format(i))
    except Exception as e:
        print(e)
    doctr_run(
        ['git',
         'push',
         'https://{token}@github.com/{deploy_repo}.git'.format(
             token=$PASSWORD, deploy_repo='regro/cf-graph'),
         'master'],
         token =$PASSWORD.encode('utf-8'))
