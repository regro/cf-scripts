#!/usr/bin/env bash

# Run this script in between bot steps to clear the runner from local artifacts.

set -euxo pipefail

rm -rf cf-graph
rm -rf conda-forge-pinning-feedstock
