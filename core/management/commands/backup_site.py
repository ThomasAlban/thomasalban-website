from django.core.management.base import BaseCommand, CommandError

from core.management.backup_utils import ERRORS, backup


class Command(BaseCommand):
    help = 'Back up SQLite and media after pausing all content editing.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--destination', required=True)
        parser.add_argument('--revision', default='unknown', help='Deployed code identifier (not a secret).')

    def handle(self, *args, **options):
        self.stderr.write('All database and media writers must remain paused until completion.')
        try:
            archive = backup(options['destination'], options['revision'])
        except ERRORS as error:
            raise CommandError(f'Backup failed: {error}') from error
        self.stdout.write(str(archive))
