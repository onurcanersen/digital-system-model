#!/bin/sh
#
# Seeds the mock Gitea with one org holding one repo per fixture software
# unit, version pushed as a git tag.
#
# Idempotent: re-running against a seeded server changes nothing.
#
# Runs as the container command: starts Gitea via s6, seeds it, then
# blocks on s6-svscan to keep the container alive.

set -eu

GITEA_URL="http://gitea:3000"
GITEA_SCHEME="${GITEA_URL%%://*}"
GITEA_HOST="${GITEA_URL#*://}"
GITEA_USER="dsm"
GITEA_PASSWORD="dsm"
GITEA_EMAIL="dsm@standin.local"
ORG="dsm-src"
SOURCE_ROOT="/dev/gitea/seed"
GITEA_CONF="/data/gitea/conf/app.ini"

log() { echo "[dsm-git-seed] $*"; }

# --- start Gitea -----------------------------------------------------------

log "starting Gitea"
chown -R git:git /etc/s6
/bin/s6-svscan /etc/s6 &
S6_PID=$!

log "waiting for ${GITEA_URL}"
until curl -sf "${GITEA_URL}/api/healthz" >/dev/null 2>&1; do
    sleep 2
done

# --- authenticate ------------------------------------------------------------

log "creating admin user '${GITEA_USER}'"
su-exec git /usr/local/bin/gitea admin user create \
    --config "${GITEA_CONF}" \
    --username "${GITEA_USER}" \
    --password "${GITEA_PASSWORD}" \
    --email "${GITEA_EMAIL}" \
    --admin 2>/dev/null || log "  user already present"

log "issuing an access token"
TOKEN=$(curl -sf -X POST "${GITEA_URL}/api/v1/users/${GITEA_USER}/tokens" \
    -u "${GITEA_USER}:${GITEA_PASSWORD}" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"dsm-seed-$(date +%s)\",\"scopes\":[\"write:organization\",\"write:repository\",\"write:user\"]}" \
    | sed -n 's/.*"sha1":"\([^"]*\)".*/\1/p')
[ -n "${TOKEN}" ] || { log "could not obtain a token"; exit 1; }

git config --global user.email "${GITEA_EMAIL}"
git config --global user.name "dsm stand-in seed"
git config --global init.defaultBranch main

# --- seed ---------------------------------------------------------------------

log "organization '${ORG}'"
curl -sf -o /dev/null -X POST "${GITEA_URL}/api/v1/orgs" \
    -H "Authorization: token ${TOKEN}" \
    -H 'content-type: application/json' \
    -d "{\"username\":\"${ORG}\"}" || log "  already present"

seed_unit() {
    # $1 unit name, $2 version tag, $3 fixture dir
    unit=$1
    version=$2
    source_dir=$3

    log "repository '${ORG}/${unit}' at ${version}"
    curl -sf -o /dev/null -X POST "${GITEA_URL}/api/v1/orgs/${ORG}/repos" \
        -H "Authorization: token ${TOKEN}" \
        -H 'content-type: application/json' \
        -d "{\"name\":\"${unit}\",\"auto_init\":false}" || log "  already present"

    work=$(mktemp -d)
    cp -R "${source_dir}/." "${work}/"
    git init -q "${work}"
    git -C "${work}" add -A
    git -C "${work}" commit -q -m "${unit} ${version}"
    git -C "${work}" tag "${version}"
    git -C "${work}" push -q --force \
        "${GITEA_SCHEME}://${GITEA_USER}:${TOKEN}@${GITEA_HOST}/${ORG}/${unit}.git" \
        HEAD:refs/heads/main "refs/tags/${version}" 2>/dev/null \
        || log "  already pushed"
    rm -rf "${work}"
}

for dir in "${SOURCE_ROOT}"/*; do
    [ -d "${dir}" ] || continue
    name=$(basename "${dir}")
    seed_unit "${name%_*}" "${name##*_}" "${dir}"
done

log "done"
wait "${S6_PID}"
