from django.db import migrations

CREATE_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION rawlisting_block_update_delete()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'RawListing is immutable: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER rawlisting_immutable
BEFORE UPDATE OR DELETE ON ingestion_rawlisting
FOR EACH ROW EXECUTE FUNCTION rawlisting_block_update_delete();
"""

DROP_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS rawlisting_immutable ON ingestion_rawlisting;
DROP FUNCTION IF EXISTS rawlisting_block_update_delete();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER_SQL, reverse_sql=DROP_TRIGGER_SQL),
    ]
