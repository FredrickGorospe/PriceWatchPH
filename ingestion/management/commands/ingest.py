import sys

from django.core.management.base import BaseCommand, CommandError

from ingestion.manual_capture import ingest_manual_capture


IMPORTERS = {
    "manual_capture": ingest_manual_capture,
}


def _read_utf8_stdin():
    stream = sys.stdin
    if hasattr(stream, "buffer"):
        try:
            return stream.buffer.read().decode("utf-8")
        except UnicodeDecodeError as error:
            raise CommandError("manual_capture input must be valid UTF-8") from error
    return stream.read()


class Command(BaseCommand):
    help = "Ingest one observation from an explicitly supported source."

    def add_arguments(self, parser):
        parser.add_argument("importer", choices=tuple(IMPORTERS))

    def handle(self, *args, **options):
        importer = IMPORTERS[options["importer"]]
        importer(_read_utf8_stdin())
