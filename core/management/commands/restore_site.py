from django.core.management.base import BaseCommand, CommandError

from core.management.backup_utils import ERRORS, restore


class Command(BaseCommand):
    help = 'Validate and restore into fresh explicit offline paths, never configured storage.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True)
        parser.add_argument('--database', required=True)
        parser.add_argument('--media-root', required=True)
        parser.add_argument('--confirm-offline', action='store_true')

    def handle(self, *args, **options):
        if not options['confirm_offline']:
            raise CommandError('--confirm-offline is mandatory; stop all users of the target paths.')
        try:
            restore(options['archive'], options['database'], options['media_root'])
        except ERRORS as error:
            raise CommandError(f'Restore failed: {error}') from error
        self.stdout.write('Restored to fresh paths. Configured storage was not changed.')
