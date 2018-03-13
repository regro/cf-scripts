#!/usr/bin/env bash

export START_TIME="$(date +%s)"
export TIMEOUT=2700
./setup.sh
cd ../cf-graph
export PATH=~/mc/bin:$PATH
xonsh ../cf-scripts/03-auto_tick.xsh
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
