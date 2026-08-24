#!/bin/sh
set -eu

for REQUIRED_PG_VAR in PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD; do
    if [ -z "$(printenv "$REQUIRED_PG_VAR")" ]; then
        printf '%s must be set and non-empty\n' "$REQUIRED_PG_VAR" >&2
        exit 2
    fi
done

umask 077

ARTIFACT="pricewatchph-$(date -u +%Y%m%dT%H%M%SZ).dump"
DUMP_TMP="/backups/.${ARTIFACT}.partial"
DIGEST_TMP="/backups/.${ARTIFACT}.sha256.partial"
FINAL="/backups/${ARTIFACT}"
CHECKSUM="${FINAL}.sha256"

if [ -e "$FINAL" ] || [ -e "$CHECKSUM" ]; then
    exit 3
fi

pg_dump -Fc -f "$DUMP_TMP"
pg_restore --list "$DUMP_TMP" >/dev/null
DIGEST="$(sha256sum "$DUMP_TMP" | cut -d ' ' -f 1)"
printf '%s  %s\n' "$DIGEST" "$ARTIFACT" > "$DIGEST_TMP"

mv "$DUMP_TMP" "$FINAL"
mv "$DIGEST_TMP" "$CHECKSUM"

[ -f "$FINAL" ]
[ -f "$CHECKSUM" ]
[ "$(wc -l < "$CHECKSUM")" -eq 1 ]
[ "$(cat "$CHECKSUM")" = "$DIGEST  $ARTIFACT" ]
(cd /backups && sha256sum -c "${ARTIFACT}.sha256" >/dev/null)
pg_restore --list "$FINAL" >/dev/null

printf 'BACKUP_ARTIFACT=%s\n' "$ARTIFACT"
