#!/usr/bin/env bash

set -euo pipefail

echo "=== mitmproxy certificates setup wizard ==="
echo "Use this shell script to setup the mitmproxy certificates for the integration tests on your machine."

# we could also add openssl to the conda environment, but this should be available on most systems
if ! command -v openssl &> /dev/null; then
    echo "error: openssl is not installed. Please install it first."
    exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mitmproxy_dir="${script_dir}/.mitmproxy"
# the mitmproxy_dir should already exist
cd "${mitmproxy_dir}"

# Headless Mode is used in GitHub Actions only
headless_mode="${MITMPROXY_WIZARD_HEADLESS:-false}"

if [ "${headless_mode}" = "true" ]; then
    echo "Running in headless mode."
    echo "The mitmproxy certificates will be generated in the directory: ${mitmproxy_dir}"

    # path to a script that will be executed after the certificates have been generated
    # the script should add the mitmproxy-ca.crt certificate to the system's trust store
    # the first argument is the path to the mitmproxy-ca.crt certificate
    headless_mode_trust_script="${MITMPROXY_WIZARD_HEADLESS_TRUST_SCRIPT}"
else
    echo "The mitmproxy certificates will be generated in the directory: ${mitmproxy_dir}"
    echo "Press enter to continue or Ctrl+C to cancel."
    read -r
fi

openssl genrsa -out mitmproxy-ca.key 4096
openssl req -x509 -new -nodes -key mitmproxy-ca.key -sha256 -days 365 -out mitmproxy-ca.crt -addext keyUsage=critical,keyCertSign -subj "/C=US/ST=cf-scripts/L=cf-scripts/O=cf-scripts/OU=cf-scripts/CN=cf-scripts"
cat mitmproxy-ca.key mitmproxy-ca.crt > mitmproxy-ca.pem

echo "The mitmproxy certificates have been generated successfully."
echo "The root certificate will be valid for 365 days."

mitmproxy_ca_crt_file="${mitmproxy_dir}/mitmproxy-ca.crt"

if [ "${headless_mode}" = "true" ]; then
    echo "Executing the headless mode trust script..."
    bash "${headless_mode_trust_script}" "${mitmproxy_ca_crt_file}"
else
    echo "You now need to trust the mitmproxy-ca.crt certificate in your system's trust store."
    echo "The exact process depends on your operating system."
    if [[ -f "/etc/debian_version" ]]; then
        echo "On Debian-based systems, you can use the following command to trust the certificate:"
        echo "sudo cp ${mitmproxy_ca_crt_file} /usr/local/share/ca-certificates/mitmproxy-ca.crt"
        echo "sudo update-ca-certificates"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "On macOS, drag and drop the mitmproxy-ca.crt file into the Keychain Access app while having the 'Login' keychain selected."
        echo "Then, double-click the certificate in the keychain and set ‘Always Trust‘ in the ‘Trust‘ section."
    fi
    echo "The certificate is located at: ${mitmproxy_ca_crt_file}"
    echo "After you're done, press enter to continue."
    read -r
fi

echo "Generating the certificate bundle mitmproxy-cert-bundle.pem to pass to Python..."
cp "$(python -m certifi)" mitmproxy-cert-bundle.pem

{
  echo ""
  echo "# cf-scripts self-signed certificate"
  cat mitmproxy-ca.crt
} >> mitmproxy-cert-bundle.pem

echo "The certificate bundle has been generated successfully."
echo "The mitmproxy certificate setup wizard has been completed successfully."
