#!/usr/bin/env bash
#
# EC2-HOST OPERATOR SCRIPT.
#
# This script is copied into both the `base` and `ai` Docker images as
# part of `scripts/` (Dockerfile's `COPY scripts ./scripts`), like every
# other operator/seed script in that directory - but it is NOT meant to
# be invoked from inside an application container: it calls `docker
# compose exec` against `stock-db`, which requires the Docker CLI and a
# working `docker compose` context that application containers don't
# have. It is NOT executed automatically by any deploy step - run it
# manually, by a human operator, on the production EC2 host itself, from
# the stock_research_system checkout root (the same directory documented
# in docs/production-deployment-runbook.md's dc() helper), never from
# inside a container, never against a local/dev database, never by
# Claude Code, and never against production from an automated context.
#
# CI never executes the backup operation and never contacts Docker or
# PostgreSQL. This repository's unit tests invoke only --help and the
# pre-Docker argument/commit/directory validation paths below (all of
# which exit before `dc` - the docker-compose wrapper - is ever called).
#
# Creates a verified, custom-format (`pg_dump -F c`) backup of the
# running "stock-db" production service and stores it outside the Git
# checkout. Never sources or prints .env; reads POSTGRES_USER/
# POSTGRES_DB from the container's own environment, not the host's;
# never runs `docker compose down -v`; never deletes existing backups.
# Restore is documented separately in
# docs/production-deployment-runbook.md - this script does not restore.
#
# Verify this script's syntax before relying on it, e.g.:
#   bash -n scripts/backup_production_database.sh
#
# Usage:
#   ./scripts/backup_production_database.sh [--backup-dir DIR] [--source-commit SHA_OR_REF]
#   ./scripts/backup_production_database.sh --help

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
BACKUP_DIR="/home/ubuntu/backups/finquest"
COMPOSE_FILE="docker-compose.production.yml"
ENV_FILE=".env"
SOURCE_COMMIT_REF="HEAD"

usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [--backup-dir DIR] [--source-commit SHA_OR_REF] [--help]

EC2-host operator script. Creates a verified PostgreSQL custom-format
(pg_dump -F c) backup of the running "stock-db" production service.

Options:
  --backup-dir DIR       Directory to store the backup in (default: ${BACKUP_DIR}).
                          Created with mode 700 if it doesn't exist. Must be
                          outside the Git checkout - rejected otherwise.
  --source-commit REF     Commit/ref that the currently RUNNING containers and
                          database correspond to (default: HEAD). Only pass
                          this explicitly when HEAD has already moved past the
                          commit the running containers were built from - e.g.
                          the first Phase A2 deployment, where this script is
                          new and doesn't exist until after "git pull", so
                          HEAD at the time this script runs is the new commit,
                          not the one the still-running containers/database
                          correspond to. Resolved and validated with
                          "git rev-parse --verify \${ref}^{commit}" before
                          anything else happens.
  --help, -h              Show this help and exit.

Must be run from the stock_research_system checkout root (the directory
containing ${COMPOSE_FILE} and ${ENV_FILE}). Never sources or prints
${ENV_FILE}. Never runs "docker compose down -v". Never deletes existing
backups - retention/cleanup is an explicit, separate operator action.
Restore is documented separately in docs/production-deployment-runbook.md.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backup-dir)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "error: --backup-dir requires a non-empty value" >&2
        exit 2
      fi
      BACKUP_DIR="$2"
      shift 2
      ;;
    --source-commit)
      if [[ $# -lt 2 || -z "${2:-}" ]]; then
        echo "error: --source-commit requires a non-empty value" >&2
        exit 2
      fi
      SOURCE_COMMIT_REF="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

dc() {
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

# Validation order below is deliberate: everything that can be checked
# from Git alone (source commit, checkout/backup-directory paths) runs
# before anything that requires .env or the Compose file, which in turn
# runs before anything that touches Docker. This keeps the Git-only
# validation paths exercisable - e.g. by this repository's unit tests -
# in a plain checkout with no .env and no Docker access at all.

# 1) Resolve and validate the source commit, so a bad ref (or the
#    first-A2-deploy case where HEAD has already moved past the running
#    commit) fails fast with a clear message rather than silently
#    mislabeling the backup.
if ! resolved_commit="$(git rev-parse --verify "${SOURCE_COMMIT_REF}^{commit}" 2>/dev/null)"; then
  echo "error: --source-commit '${SOURCE_COMMIT_REF}' does not resolve to a commit" >&2
  exit 1
fi
commit_short="${resolved_commit:0:12}"

# 2) Resolve the Git checkout root and the requested backup directory to
#    absolute, symlink-resolved paths, both anchored to the same
#    *physical* (symlink-resolved) working directory - `pwd -P`, not
#    plain `pwd`/`realpath`'s implicit logical cwd - so the two can be
#    compared as plain strings below. Two path-form mismatches are
#    possible on non-Linux dev hosts (neither applies on a plain Linux
#    EC2 host, where `pwd`, `pwd -P`, and `git rev-parse --show-toplevel`
#    always agree): (a) `git rev-parse --show-toplevel` can emit a
#    drive-letter path (Git-for-Windows/Cygwin) while `pwd` is
#    POSIX-style - fixed by routing it through `cd`+`pwd -P`; (b) a
#    relative `--backup-dir` resolved by plain `realpath -m` is anchored
#    to the *logical* cwd, which can itself differ from the *physical*
#    one when a path component is a symlink (e.g. Cygwin's `/tmp`) -
#    fixed by anchoring relative input to `pwd -P` before calling
#    `realpath -m`.
physical_cwd="$(pwd -P)"
case "${BACKUP_DIR}" in
  /*) backup_dir_input="${BACKUP_DIR}" ;;
  *) backup_dir_input="${physical_cwd}/${BACKUP_DIR}" ;;
esac
repo_root="$(cd "$(git rev-parse --show-toplevel)" && pwd -P)"
resolved_backup_dir="$(realpath -m "${backup_dir_input}")"
resolved_repo_root="$(realpath -m "${repo_root}")"

# 3) Reject a backup directory equal to, or nested under, the checkout.
case "${resolved_backup_dir}/" in
  "${resolved_repo_root}/"*)
    echo "error: --backup-dir (${resolved_backup_dir}) is inside the Git checkout (${resolved_repo_root}) - backups must be stored outside it, e.g. /home/ubuntu/backups/finquest." >&2
    exit 1
    ;;
esac

# 4) Check .env.
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} not found in $(pwd) - run this from the stock_research_system checkout root." >&2
  exit 1
fi

# 5) Check docker-compose.production.yml.
if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "error: ${COMPOSE_FILE} not found in $(pwd) - run this from the stock_research_system checkout root." >&2
  exit 1
fi

# 6) Only now access Docker and validate stock-db health. An exact "(healthy)"
#    marker match, not a substring match on "healthy" - the latter would also
#    match Compose's own "(unhealthy)" status text.
stock_db_status="$(dc ps stock-db)"
if ! grep -qE '\(healthy\)' <<< "${stock_db_status}"; then
  echo "error: stock-db is not reporting healthy. Run 'dc ps stock-db' to inspect it." >&2
  exit 1
fi

mkdir -p "${resolved_backup_dir}"
chmod 700 "${resolved_backup_dir}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_file="${resolved_backup_dir}/stock_db_${timestamp}_${commit_short}.dump"
tmp_file="${final_file}.tmp"

# Guarded cleanup: only ever removes the *temporary* file, and only while
# tmp_file still points at one. After a successful verified rename below,
# tmp_file is cleared so this trap can never touch the final backup.
#
# A trapped INT/TERM alone would replace Bash's default terminating
# behavior for those signals, so the script could in principle continue
# past them - instead, EXIT always runs the guarded cleanup, and INT/TERM
# each explicitly `exit` with their conventional (128+signal) status,
# which itself triggers the EXIT trap.
cleanup() {
  if [[ -n "${tmp_file:-}" && -f "${tmp_file}" ]]; then
    rm -f -- "${tmp_file}"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

touch "${tmp_file}"
chmod 600 "${tmp_file}"

# 1) Stream pg_dump's stdout from inside the stock-db container into the
#    host-side temp file. `exec` replaces the wrapping shell with
#    pg_dump so this command's exit status is pg_dump's own exact exit
#    status. POSTGRES_USER/POSTGRES_DB are read from the container's own
#    environment - never copied into a host variable, never echoed.
echo "Dumping stock-db to a temporary host file (not yet verified): ${tmp_file}"
dc exec -T stock-db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -F c' > "${tmp_file}"

# 2) Verify by piping the host temp file into pg_restore --list running
#    inside the container, via stdin - never pass a host path as an
#    argument to a command running inside the container.
echo "Verifying the dump with pg_restore --list inside stock-db..."
dc exec -T stock-db pg_restore --list < "${tmp_file}" > /dev/null

# 3) Only after verification succeeds: atomic, non-clobbering rename to
#    the final name, then clear tmp_file so the cleanup trap becomes a
#    no-op. This script never deletes existing backups, so an existing
#    file at the destination name must never be overwritten - checked
#    both before the move (fast, clear error) and after it via `mv -n`
#    (no-clobber) plus confirming the temp file no longer exists
#    (belt-and-braces against a race between the check and the move).
#    tmp_file is only cleared once the move is confirmed successful, so
#    a failed/refused move leaves the EXIT trap free to clean up only
#    the still-existing temp file - the pre-existing final_file it
#    refused to touch is never removed either.
if [[ -e "${final_file}" ]]; then
  echo "error: refusing to overwrite an existing backup: ${final_file}" >&2
  exit 1
fi

echo "Verification passed. Renaming to the final backup filename..."
mv -n -- "${tmp_file}" "${final_file}"
if [[ -e "${tmp_file}" ]]; then
  echo "error: an existing backup at ${final_file} was not overwritten (no-clobber move left ${tmp_file} in place) - refusing to continue." >&2
  exit 1
fi
tmp_file=""
chmod 600 "${final_file}"

echo "Backup created: ${final_file}"
echo "Source commit: ${resolved_commit} (recorded in filename as ${commit_short})"
echo "This script does not delete old backups and does not restore - see docs/production-deployment-runbook.md."
