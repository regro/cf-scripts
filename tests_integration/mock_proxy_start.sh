#!/usr/bin/env bash

set -euo pipefail

# If debugging locally, set PROXY_DEBUG_LOGGING to true to show full HTTP request/response details.
# We can't enable this in GitHub Actions because it will expose GitHub secrets.
PROXY_DEBUG_LOGGING=${PROXY_DEBUG_LOGGING:-false}

if [[ "${PROXY_DEBUG_LOGGING}" == "true" ]]; then
  flow_detail=4
else
  flow_detail=0
fi

if [[ -z "$MITMPROXY_CONFDIR" ]]; then
  echo "Set $MITMPROXY_CONFDIR to a directory containing a mitmproxy-ca.pem CA certificate to intercept HTTPS traffic."
  exit 1
fi

# You might need to set PYTHONPATH to the root of cf-scripts
mitmdump -s ./mock_server_addon.py \
  --flow-detail "$flow_detail" \
  --set confdir="$MITMPROXY_CONFDIR" \
  --set connection_strategy=lazy \
  --set upstream_cert=false 2>&1 | tee /tmp/mitmproxy.log
