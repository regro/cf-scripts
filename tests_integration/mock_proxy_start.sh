#!/usr/bin/env bash

set -euxo pipefail

# If debugging locally, set PROXY_DEBUG_LOGGING to true to show full HTTP request/response details.
# We can't enable this in GitHub Actions because it will expose GitHub secrets.
PROXY_DEBUG_LOGGING=${PROXY_DEBUG_LOGGING:-false}

if [[ "${PROXY_DEBUG_LOGGING}" == "true" ]]; then
  flow_detail=4
else
  flow_detail=0
fi

if [[ -z "$MITMPROXY_PEM" ]]; then
  echo "Set MITMPROXY_PEM to the path of a certificate that mitmproxy uses to intercept TLS traffic."
  exit 1
fi

# You might need to set PYTHONPATH to the root of cf-scripts
mitmdump -s ./mock_server_addon.py \
  --flow-detail "$flow_detail" \
  --certs '*'="$MITMPROXY_PEM" \
  --set connection_strategy=lazy \
  --set upstream_cert=false 2>&1 | tee /tmp/mitmproxy.log
