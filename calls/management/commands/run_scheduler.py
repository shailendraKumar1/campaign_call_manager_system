from django.core.management.base import BaseCommand
from django.conf import settings
import logging
from calls.scheduler import run_scheduler

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run the retry scheduler for failed calls'

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=1,
            help='Scheduler check interval in minutes (default: 1)'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting retry scheduler...')
        )
        
        try:
            run_scheduler()
        except KeyboardInterrupt:
            self.stdout.write(
                self.style.WARNING('Scheduler stopped by user')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Scheduler error: {str(e)}')
            )
            logger.error(f'Scheduler error: {str(e)}')
