#!/usr/bin/env bash

./setup.sh
cd ../cf-graph
export PATH=~/mc/bin:$PATH
conda-forge-tick --run 0
conda-forge-tick --run 1
echo "$(pwd)"
#doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
