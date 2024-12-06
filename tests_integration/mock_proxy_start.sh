#!/usr/bin/env bash

set -euxo pipefail

# You might need to set PYTHONPATH to the root of cf-scripts
mitmdump -s ./tests_integration/mock_server_addon.py --set connection_strategy=lazy --set upstream_cert=false 2>&1 | tee /tmp/mitmproxy.log