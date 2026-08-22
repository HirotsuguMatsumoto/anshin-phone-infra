#!/bin/sh
set -eu

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$#" -ne 2 ] || [ "$1" != "--execute" ]; then
  echo "Usage: $0 --execute /absolute/protected/backup-directory" >&2
  echo "No backup was created. This script requires an explicit execution flag." >&2
  exit 2
fi

case "$2" in
  /*) output_dir=$2 ;;
  *) echo "backup directory must be absolute" >&2; exit 2 ;;
esac
case "$output_dir" in
  "$repo_dir"|"$repo_dir"/*) echo "backup directory must be outside the repository" >&2; exit 2 ;;
esac

umask 077
mkdir -p "$output_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$output_dir/$timestamp"
mkdir "$target"

docker compose -f "$repo_dir/compose.phase1.yaml" ps --format json > "$target/compose-ps.json"
docker compose -f "$repo_dir/compose.phase1.yaml" images --format json > "$target/compose-images.json"
docker compose -f "$repo_dir/compose.phase1.yaml" exec -T postgres \
  pg_dump --format=custom --no-owner --username=anshin_phone anshin_phone > "$target/postgres.dump"
git -C "$repo_dir" rev-parse HEAD > "$target/infra-head.txt"
git -C "$repo_dir/anshin-phone-backend" rev-parse HEAD > "$target/backend-head.txt"
shasum -a 256 "$target"/* > "$target/SHA256SUMS"
chmod -R go-rwx "$target"
echo "Phase 1 backup created: $target"
echo "Verify restore in an isolated environment before treating it as recoverable."
