from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from calls.consumer import DLQProcessor
from calls.models import DLQEntry
from config import Config


class Command(BaseCommand):
    help = 'Clean up old DLQ entries and process unprocessed ones'

    def add_arguments(self, parser):
        parser.add_argument(
            '--process-unprocessed',
            action='store_true',
            help='Process unprocessed DLQ entries'
        )
        parser.add_argument(
            '--cleanup-old',
            action='store_true',
            help='Clean up old processed DLQ entries'
        )
        parser.add_argument(
            '--retention-days',
            type=int,
            default=Config.DLQ_RETENTION_DAYS,
            help=f'Retention period in days (default: {Config.DLQ_RETENTION_DAYS})'
        )

    def handle(self, *args, **options):
        if options['process_unprocessed']:
            self.stdout.write('Processing unprocessed DLQ entries...')
            DLQProcessor.process_dlq_entries()
            self.stdout.write(
                self.style.SUCCESS('Finished processing unprocessed DLQ entries')
            )
        
        if options['cleanup_old']:
            retention_days = options['retention_days']
            cutoff_date = timezone.now() - timedelta(days=retention_days)
            
            self.stdout.write(f'Cleaning up DLQ entries older than {retention_days} days...')
            
            deleted_count = DLQEntry.objects.filter(
                processed=True,
                processed_at__lt=cutoff_date
            ).delete()[0]
            
            self.stdout.write(
                self.style.SUCCESS(f'Cleaned up {deleted_count} old DLQ entries')
            )
        
        if not options['process_unprocessed'] and not options['cleanup_old']:
            # Default: do both
            self.stdout.write('Processing unprocessed DLQ entries...')
            DLQProcessor.process_dlq_entries()
            
            self.stdout.write('Cleaning up old DLQ entries...')
            DLQProcessor.cleanup_old_dlq_entries()
            
            self.stdout.write(
                self.style.SUCCESS('DLQ cleanup completed')
            )
