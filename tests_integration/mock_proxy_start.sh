#!/usr/bin/env bash

set -euxo pipefail

# If debugging locally, set DEBUG_PROXY_SERVER to true.
# We can't enable this in GitHub Actions because it will expose GitHub secrets.
PROXY_DEBUG_LOGGING=${PROXY_DEBUG_LOGGING:-false}

if [[ "${PROXY_DEBUG_LOGGING}" == "true" ]]; then
  flow_detail=4
else
  flow_detail=0
fi

# You might need to set PYTHONPATH to the root of cf-scripts
mitmdump -s ./tests_integration/mock_server_addon.py \
  --flow-detail "$flow_detail" \
  --set connection_strategy=lazy \
  --set upstream_cert=false 2>&1 | tee /tmp/mitmproxy.log
