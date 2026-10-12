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

: "${COMPOSE_FILE:=$repo_dir/compose.phase1.yaml}"
export COMPOSE_FILE
backend_root=$(python3 "$repo_dir/scripts/resolve_phone_backend.py" --infra-root "$repo_dir" ${ANSHIN_PHONE_BACKEND_DIR:+--override "$ANSHIN_PHONE_BACKEND_DIR"})

docker compose ps --format json > "$target/compose-ps.json"
docker compose images --format json > "$target/compose-images.json"
docker compose exec -T postgres \
  pg_dump --format=custom --no-owner --username=anshin_phone anshin_phone > "$target/postgres.dump"
# Callers quiesce their owned producers before this snapshot. The key is
# deliberately excluded: only already encrypted originals enter the backup.
backend_container=$(docker compose ps --quiet backend)
backend_image=$(docker inspect --format '{{.Config.Image}}' "$backend_container")
docker run --rm --network none --volumes-from "$backend_container:ro" \
  --entrypoint tar "$backend_image" -cf - -C /var/lib/anshin-phone/fax . > "$target/fax-encrypted.tar"
git -C "$repo_dir" rev-parse HEAD > "$target/infra-head.txt"
git -C "$backend_root" rev-parse HEAD > "$target/backend-head.txt"
shasum -a 256 "$target"/* > "$target/SHA256SUMS"
chmod -R go-rwx "$target"
echo "Phase 1 backup created: $target"
echo "Verify restore in an isolated environment before treating it as recoverable."
