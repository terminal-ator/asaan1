#!/usr/bin/env sh
# Build the PWA on this machine, ship the code and dist/ to the server, then
# deploy there. The VPS never needs Node.
#
#   deploy/ship.sh <user@host>              # build, ship, deploy
#   SKIP_DEPLOY=1 deploy/ship.sh <user@host> # first push before bootstrap
#   DRY_RUN=1 deploy/ship.sh <user@host>     # show what would change
#
# Useful variables:
#   APP_DIR=/opt/asaan APP_USER=asaan   server paths (must match the bootstrap)
#   SSH_OPTS="-i ~/.ssh/asaan_deploy"   extra ssh options
#   RSYNC_SSH=ssh                       ssh command used by rsync
set -eu

TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "usage: deploy/ship.sh <user@host>" >&2; exit 1; }

APP_DIR="${APP_DIR:-/opt/asaan}"
APP_USER="${APP_USER:-asaan}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
RSYNC_SSH="${RSYNC_SSH:-ssh}"
SSH_OPTS="${SSH_OPTS:-}"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# OVH and similar providers hand you root; anything else needs sudo for the
# rsync receiver and the remote deploy.
case "$TARGET" in
  root@*) REMOTE_RSYNC="rsync"; REMOTE_SUDO="" ;;
  *) REMOTE_RSYNC="sudo rsync"; REMOTE_SUDO="sudo " ;;
esac

say() { printf '\n==> %s\n' "$1"; }

cd "$LOCAL_DIR"

if [ -d .git ] && [ -n "$(git status --porcelain)" ]; then
  echo "warning: the working tree has uncommitted changes. They will be shipped,"
  echo "         but a server-side rollback restores the last commit, not them."
fi

say "building the PWA here"
npm run build

say "shipping code and dist to $TARGET:$APP_DIR"
# .git is left alone: the server keeps its own history, remote and deploy key.
ship() {
  rsync -az --delete -e "$RSYNC_SSH $SSH_OPTS" \
    --rsync-path="$REMOTE_RSYNC" --chown="$APP_USER:$APP_USER" \
    --exclude=node_modules \
    --exclude=django_api/.venv \
    --exclude=__pycache__ \
    --exclude='*.pyc' \
    --exclude='*.tsbuildinfo' \
    --exclude=django_api/db.sqlite3 \
    --exclude=django_api/media \
    --exclude=django_api/staticfiles \
    --exclude=uploads \
    --exclude=.env.local \
    --exclude=.git \
    "$@" ./ "$TARGET:$APP_DIR/"
}
if [ "$DRY_RUN" = "1" ]; then ship --dry-run; else ship; fi

if [ "$DRY_RUN" = "1" ]; then
  say "dry run: not deploying"
  exit 0
fi

if [ "$SKIP_DEPLOY" = "1" ]; then
  say "code shipped; skipping the server-side deploy"
  exit 0
fi

say "deploying on the server"
# shellcheck disable=SC2029
ssh $SSH_OPTS "$TARGET" \
  "${REMOTE_SUDO}APP_DIR='$APP_DIR' APP_USER='$APP_USER' SKIP_FRONTEND=1 sh '$APP_DIR/deploy/deploy.sh'"

say "done"
