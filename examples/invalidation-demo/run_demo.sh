#!/usr/bin/env bash
# Offline demo of the invalidation engine on invented data.
# Copies the engine and a toy project to a temp dir, snapshots the ledgers,
# edits one quotation, and asks the engine what became STALE.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd -P)
REPO=$(cd "$HERE/../.." && pwd -P)
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/tools"
cp -R "$REPO/tools/invalidation" "$W/tools/invalidation"
cp -R "$HERE/project/." "$W/"
mkdir "$W/snapshot"
cp "$W/research/quote_ledger.csv" "$W/research/claim_ledger.csv" "$W/Sources/source_manifest.json" "$W/snapshot/"
# The one-time schema migration adds content_hash and engine_status columns.
python3 "$W/tools/invalidation/invalidation.py" migrate-schema --apply >/dev/null
cp "$W/research/quote_ledger.csv" "$W/research/claim_ledger.csv" "$W/Sources/source_manifest.json" "$W/snapshot/"
# Correct the wording of one quotation (q-002) in the live ledger.
sed -i.bak 's/fell below half in year two/fell below forty percent in year two/' "$W/research/quote_ledger.csv"
rm "$W/research/quote_ledger.csv.bak"
echo "== check: what does that edit make STALE?"
python3 "$W/tools/invalidation/invalidation.py" check --against "$W/snapshot"
