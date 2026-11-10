#!/bin/zsh
# Run the Apple WeMM helper on the host so a Docker container can use it.
# The helper keeps listening on host loopback only; Docker Desktop and OrbStack
# let containers reach it as http://host.docker.internal:<port>.
#
# Usage: scripts/run-host-embedding-helper.sh /path/to/model-package [port]
set -eu

root="${0:A:h:h}"
package="${1:?usage: $0 /path/to/model-package [port]}"
port="${2:-18790}"
binary="${INDEXED_APPLE_EMBEDDING_BINARY:-$root/native/apple-embedding/dist/apple-silicon/indexed-apple-embedding}"
home="${INDEXED_HOME:-$HOME/.config/indexed}"
tokenfile="$home/host-helper.token"

[[ -x "$binary" ]] || { print -u2 "Missing helper binary: $binary (run native/apple-embedding/build_native_service.sh)"; exit 1; }
[[ -d "$package" ]] || { print -u2 "Model package not found: $package"; exit 1; }

# Video indexing requires the profile's space ID to equal the helper's own embedding
# space, which comes from the package manifest. Fill in the dimension placeholder.
space="$(node -e '
const m = JSON.parse(require("fs").readFileSync(process.argv[1] + "/manifest.json", "utf8"));
process.stdout.write(String(m.embedding_space_template || "").replace("{dimension}", "2048"));
' "$package")"
[[ -n "$space" ]] || { print -u2 "No embedding_space_template in $package/manifest.json"; exit 1; }

# Reuse one token so the profile saved in the dashboard stays valid across runs.
if [[ ! -s "$tokenfile" ]]; then
  mkdir -p "$home"
  (umask 077; openssl rand -hex 24 > "$tokenfile")
fi

cat <<INFO
Dashboard profile (embedding provider: remote):
  Service URL : http://host.docker.internal:$port
  API key     : $(<"$tokenfile")
  Model       : wemm-embedding-2b-apple-2048
  Dimension   : 2048
  Input style : wemm
  Space ID    : $space
INFO

export INDEXED_APPLE_EMBEDDING_AUTH_TOKEN="$(<"$tokenfile")"
exec "$binary" serve \
  --package "$package" \
  --port "$port" \
  --default-dimension 2048 \
  --execution-mode b \
  --vision-compute ane \
  --language-compute gpu
