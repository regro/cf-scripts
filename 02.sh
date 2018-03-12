#!/usr/bin/env bash

./setup.sh
conda-forge-tick --run 2
doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .
