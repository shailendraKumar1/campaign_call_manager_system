from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from calls.models import CallLog, CallMetrics
from calls.utils import MetricsManager


class Command(BaseCommand):
    help = 'Generate daily metrics from call logs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to generate metrics for (YYYY-MM-DD format). Default: today'
        )
        parser.add_argument(
            '--backfill-days',
            type=int,
            help='Number of days to backfill metrics for'
        )

    def handle(self, *args, **options):
        if options['backfill_days']:
            # Backfill metrics for multiple days
            days = options['backfill_days']
            self.stdout.write(f'Backfilling metrics for the last {days} days...')
            
            for i in range(days):
                target_date = date.today() - timedelta(days=i)
                self.generate_metrics_for_date(target_date)
            
            self.stdout.write(
                self.style.SUCCESS(f'Backfilled metrics for {days} days')
            )
        else:
            # Generate for specific date or today
            if options['date']:
                try:
                    target_date = date.fromisoformat(options['date'])
                except ValueError:
                    self.stdout.write(
                        self.style.ERROR('Invalid date format. Use YYYY-MM-DD')
                    )
                    return
            else:
                target_date = date.today()
            
            self.generate_metrics_for_date(target_date)
            self.stdout.write(
                self.style.SUCCESS(f'Generated metrics for {target_date}')
            )

    def generate_metrics_for_date(self, target_date):
        """Generate metrics for a specific date"""
        self.stdout.write(f'Generating metrics for {target_date}...')
        
        # Get all calls for the date
        calls = CallLog.objects.filter(
            created_at__date=target_date
        )
        
        # Calculate metrics
        total_initiated = calls.count()
        total_picked = calls.filter(status='PICKED').count()
        total_disconnected = calls.filter(status='DISCONNECTED').count()
        total_rnr = calls.filter(status='RNR').count()
        total_failed = calls.filter(status='FAILED').count()
        total_retries = calls.filter(attempt_count__gt=1).count()
        
        # Calculate total call duration
        total_duration = sum(
            call.total_call_time or 0 
            for call in calls 
            if call.total_call_time
        )
        
        # Create or update metrics
        metrics, created = CallMetrics.objects.get_or_create(
            date=target_date,
            defaults={
                'total_calls_initiated': total_initiated,
                'total_calls_picked': total_picked,
                'total_calls_disconnected': total_disconnected,
                'total_calls_rnr': total_rnr,
                'total_calls_failed': total_failed,
                'total_retries': total_retries,
                'total_call_duration_seconds': total_duration,
                'peak_concurrent_calls': 0,  # Would need to calculate from logs
                'dlq_entries_created': 0,    # Would need to calculate from DLQ
            }
        )
        
        if not created:
            # Update existing metrics
            metrics.total_calls_initiated = total_initiated
            metrics.total_calls_picked = total_picked
            metrics.total_calls_disconnected = total_disconnected
            metrics.total_calls_rnr = total_rnr
            metrics.total_calls_failed = total_failed
            metrics.total_retries = total_retries
            metrics.total_call_duration_seconds = total_duration
            metrics.save()
        
        self.stdout.write(f'  Initiated: {total_initiated}')
        self.stdout.write(f'  Picked: {total_picked}')
        self.stdout.write(f'  Disconnected: {total_disconnected}')
        self.stdout.write(f'  RNR: {total_rnr}')
        self.stdout.write(f'  Failed: {total_failed}')
        self.stdout.write(f'  Retries: {total_retries}')
        self.stdout.write(f'  Total Duration: {total_duration}s')
