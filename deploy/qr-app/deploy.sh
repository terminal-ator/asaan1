#!/usr/bin/env sh
# Deploy the QR Shops SPA.
#
# The app is a static Create React App build with no server of its own: its
# GraphQL calls go to /gql, which the ProBooks API serves. This script pulls
# the build from the old Lightsail box, copies it to the OVH server, and makes
# sure its Caddy site exists (replacing only the marked qr section).
#
#   deploy/qr-app/deploy.sh
#   SRC=ubuntu@13.233.243.133 DEST=ubuntu@51.79.144.234 deploy/qr-app/deploy.sh
set -eu

SRC="${SRC:-ubuntu@13.233.243.133}"
DEST="${DEST:-ubuntu@51.79.144.234}"
SRC_KEY="${SRC_KEY:-$HOME/Downloads/sshnow.pem}"
DEST_KEY="${DEST_KEY:-$HOME/.ssh/asaan_deploy}"
SRC_DIR="${SRC_DIR:-/var/www/qr.rologe.com}"
REMOTE_DIR="${REMOTE_DIR:-/var/www/qr.asaan.in}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
HERE="$(cd "$(dirname "$0")" && pwd)"

say() { printf '\n==> %s\n' "$1"; }

say "pulling the build from $SRC:$SRC_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
rsync -a -e "ssh -i $SRC_KEY" "$SRC:$SRC_DIR/" "$TMP/"

say "copying to $DEST:$REMOTE_DIR"
ssh -i "$DEST_KEY" "$DEST" "sudo install -d -o root -g root -m 755 '$REMOTE_DIR'"
rsync -a --delete --rsync-path="sudo rsync" -e "ssh -i $DEST_KEY" "$TMP/" "$DEST:$REMOTE_DIR/"

say "updating the Caddy site"
ssh -i "$DEST_KEY" "$DEST" "
set -eu
sudo cp -a '$CADDYFILE' '$CADDYFILE.bak-qr-\$(date +%Y%m%d%H%M%S)'
sudo sed -i '/# >>> qr/,/# <<< qr/d' '$CADDYFILE'
sudo tee -a '$CADDYFILE' >/dev/null
if ! sudo caddy validate --config '$CADDYFILE' >/dev/null 2>&1; then
  latest=\$(ls -t '$CADDYFILE'.bak-qr-* | head -1)
  sudo cp -a \"\$latest\" '$CADDYFILE'
  echo 'caddy config did not validate; previous file restored' >&2
  exit 1
fi
sudo systemctl reload caddy
echo '  caddy reloaded'
" < "$HERE/Caddyfile.qr"

say "done"
