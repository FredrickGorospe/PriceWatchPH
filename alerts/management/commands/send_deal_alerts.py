"""The scheduler-facing alert command.

Owns only argument handling, the summary line, and the exit status; every
eligibility, claiming, and transition rule lives in alerts/orchestration.py.
See tasks/TASK_032_ALERT_SEND_ORCHESTRATION_AND_COMMAND.md Section 10.
"""

from django.core.management.base import BaseCommand, CommandError

from alerts.config import AlertConfigurationError, alerts_enabled
from alerts.orchestration import send_pending_deal_alerts


class Command(BaseCommand):
    help = "Send Telegram alerts for eligible DealFlags, claiming each exactly once."

    def add_arguments(self, parser):
        # No arguments in v1: no --force, --limit, --dry-run, or --resend.
        # Abbreviation is switched off because argparse would otherwise accept
        # `--force` as a prefix of Django's base `--force-color`, silently
        # running the command instead of rejecting an option it does not have.
        parser.allow_abbrev = False

    def handle(self, *args, **options):
        # Checked here as well as in the service so a disabled run leaves a
        # visible operational trace instead of an ordinary zeroed summary.
        if not alerts_enabled():
            self.stdout.write("Alerts disabled: no deal flags were considered.")
            return

        try:
            summary = send_pending_deal_alerts()
        except AlertConfigurationError as error:
            # TASK_031's configuration messages name the setting, never its
            # value, so re-using the text leaks no credential.
            raise CommandError(str(error)) from error

        # Written before any failure is raised, so an operator always sees the
        # counts even on a non-zero exit.
        self.stdout.write(
            f"Alerts complete: candidates={summary.candidates} "
            f"sent={summary.sent} failed={summary.failed}"
        )

        if summary.failed > 0:
            # CommandError is this repository's only non-zero-exit mechanism;
            # cron needs the bad run to surface (docs/07_PLANNING.md §8).
            raise CommandError("Alert delivery completed with failures.")
