#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

n8n_images="$(docker compose config --images | awk '/^n8nio\/n8n:/{print}')"
n8n_image_count="$(printf '%s\n' "$n8n_images" | awk 'NF { count += 1 } END { print count + 0 }')"

if [[ "$n8n_image_count" != "1" ]]; then
  echo "Expected exactly one Compose-pinned n8n image; found $n8n_image_count." >&2
  exit 1
fi

n8n_image="$(printf '%s\n' "$n8n_images" | awk 'NF { print; exit }')"
if [[ "$n8n_image" != n8nio/n8n:2.35.5@sha256:* ]]; then
  echo "The Compose n8n image must remain version 2.35.5 and digest-pinned." >&2
  exit 1
fi

docker pull "$n8n_image" >/dev/null

log_directory="$(mktemp -d "${TMPDIR:-/tmp}/finary-n8n-import.XXXXXX")"
trap 'rm -rf "$log_directory"' EXIT

workflows=(
  "n8n/workflows/finary-daily-sync.json"
  "n8n/workflows/finary-error-handler.json"
)

for workflow in "${workflows[@]}"; do
  log_file="$log_directory/$(basename "$workflow").log"
  if ! docker run --rm --pull never --network none \
    -e N8N_USER_FOLDER=/tmp/n8n-ci \
    -e N8N_ENCRYPTION_KEY=ci-only-synthetic-import-key \
    -e N8N_DIAGNOSTICS_ENABLED=false \
    -e N8N_PERSONALIZATION_ENABLED=false \
    --mount "type=bind,src=$repository_root/$workflow,dst=/tmp/workflow.json,readonly" \
    "$n8n_image" import:workflow --input=/tmp/workflow.json \
    >"$log_file" 2>&1; then
    cat "$log_file" >&2
    exit 1
  fi

  if ! grep -Fq "Successfully imported 1 workflow." "$log_file"; then
    cat "$log_file" >&2
    echo "n8n did not confirm a successful import for $workflow." >&2
    exit 1
  fi

  printf 'validated n8n import: %s\n' "$workflow"
done
