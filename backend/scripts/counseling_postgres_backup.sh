#!/usr/bin/env bash
set -euo pipefail

action="${1:-}"
archive="${2:-}"
if [[ -z "$action" || -z "$archive" ]]; then
  echo "usage: $0 {export|drill} /absolute/path/to/yuxi.dump" >&2
  exit 2
fi
if [[ "$archive" != /* ]]; then
  echo "archive path must be absolute" >&2
  exit 2
fi

manifest="${archive}.manifest.json"
expected_versions=$'business=9\ncounseling=5\nknowledge=2'

case "$action" in
  export)
    archive_parent="$(dirname "$archive")"
    if [[ ! -d "$archive_parent" ]]; then
      echo "archive parent directory does not exist" >&2
      exit 2
    fi
    archive_tmp="$(mktemp "$archive_parent/.counseling-postgres.XXXXXX.dump")"
    manifest_tmp="$(mktemp "$archive_parent/.counseling-postgres.XXXXXX.manifest")"
    cleanup_export() {
      rm -f -- "$archive_tmp" "$manifest_tmp"
    }
    trap cleanup_export EXIT
    versions="$(docker compose exec -T postgres psql -U postgres -d yuxi -Atc "SELECT domain || '=' || version FROM yuxi_schema_migrations ORDER BY domain;")"
    if [[ "$versions" != "$expected_versions" ]]; then
      echo "source PostgreSQL schema versions are not current" >&2
      exit 1
    fi
    server_version="$(docker compose exec -T postgres psql -U postgres -d yuxi -Atc "SHOW server_version_num;")"
    docker compose exec -T postgres pg_dump -U postgres -d yuxi -Fc >"$archive_tmp"
    if [[ ! -s "$archive_tmp" ]]; then
      echo "PostgreSQL backup is empty" >&2
      exit 1
    fi
    archive_sha256="$(sha256sum "$archive_tmp" | cut -d ' ' -f 1)"
    archive_size="$(stat -c '%s' "$archive_tmp")"
    printf '{\n  "format_version": 1,\n  "source_database": "yuxi",\n  "source_server_version_num": "%s",\n  "archive_sha256": "%s",\n  "archive_size": %s,\n  "schema_versions": {"business": 9, "counseling": 5, "knowledge": 2}\n}\n' \
      "$server_version" "$archive_sha256" "$archive_size" >"$manifest_tmp"
    mv -f -- "$archive_tmp" "$archive"
    mv -f -- "$manifest_tmp" "$manifest"
    trap - EXIT
    ;;
  drill)
    if [[ ! -s "$archive" || ! -s "$manifest" ]]; then
      echo "PostgreSQL backup or manifest is missing or empty" >&2
      exit 2
    fi
    manifest_fields="$(python3 -c '
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        data = json.load(source)
except (OSError, ValueError) as exc:
    raise SystemExit("manifest JSON is invalid") from exc
required = {
    "format_version",
    "source_database",
    "source_server_version_num",
    "archive_sha256",
    "archive_size",
    "schema_versions",
}
if set(data) != required:
    raise SystemExit("manifest fields are not exact")
if data["schema_versions"] != {"business": 9, "counseling": 5, "knowledge": 2}:
    raise SystemExit("manifest schema versions are not current")
print(
    data["format_version"],
    data["source_database"],
    data["source_server_version_num"],
    data["archive_sha256"],
    data["archive_size"],
    sep="\t",
)
' "$manifest")"
    IFS=$'\t' read -r format_version source_database source_server_version archive_sha256 archive_size <<<"$manifest_fields"
    if [[ "$format_version" != "1" || "$source_database" != "yuxi" || ! "$source_server_version" =~ ^[0-9]+$ ]]; then
      echo "PostgreSQL backup manifest identity is invalid" >&2
      exit 1
    fi
    actual_sha256="$(sha256sum "$archive" | cut -d ' ' -f 1)"
    actual_size="$(stat -c '%s' "$archive")"
    if [[ "$actual_sha256" != "$archive_sha256" || "$actual_size" != "$archive_size" ]]; then
      echo "PostgreSQL backup does not match manifest" >&2
      exit 1
    fi

    target="counseling_restore_${RANDOM}_$$"
    cleanup() {
      docker compose exec -T postgres dropdb -U postgres --if-exists "$target" >/dev/null
    }
    trap cleanup EXIT
    docker compose exec -T postgres createdb -U postgres "$target"
    docker compose exec -T postgres pg_restore -U postgres -d "$target" --exit-on-error --no-owner --no-privileges <"$archive"
    tables="$(docker compose exec -T postgres psql -U postgres -d "$target" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';")"
    versions="$(docker compose exec -T postgres psql -U postgres -d "$target" -Atc "SELECT domain || '=' || version FROM yuxi_schema_migrations ORDER BY domain;")"
    restored_server_version="$(docker compose exec -T postgres psql -U postgres -d "$target" -Atc "SHOW server_version_num;")"
    required_tables="$(docker compose exec -T postgres psql -U postgres -d "$target" -Atc "SELECT count(*) FROM unnest(ARRAY['users','conversations','agent_runs','counseling_students','counseling_records','counseling_materials','counseling_data_use_acknowledgments']) AS name WHERE to_regclass('public.' || name) IS NOT NULL;")"
    trigger="$(docker compose exec -T postgres psql -U postgres -d "$target" -Atc "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_counseling_notice_immutable' AND tgenabled = 'O';")"
    if [[ "$restored_server_version" != "$source_server_version" || "$versions" != "$expected_versions" || "$required_tables" != "7" || "$trigger" != "1" ]]; then
      echo "restored PostgreSQL invariants are incomplete" >&2
      exit 1
    fi
    printf 'restored_database=%s\npublic_tables=%s\nschema_versions=%s\nrequired_tables=%s\nnotice_trigger=%s\n' \
      "$target" "$tables" "$versions" "$required_tables" "$trigger"
    ;;
  *)
    echo "unsupported action: $action" >&2
    exit 2
    ;;
esac
