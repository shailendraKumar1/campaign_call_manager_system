from django.core.management.base import BaseCommand
import logging
import threading
import time
from calls.consumer import start_initiated_call_consumer, start_callback_consumer, stop_consumers

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Run Kafka consumers for call events'

    def add_arguments(self, parser):
        parser.add_argument(
            '--consumer',
            choices=['initiate', 'callback', 'all'],
            default='all',
            help='Which consumer to run (default: all)'
        )

    def handle(self, *args, **options):
        consumer_type = options['consumer']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting {consumer_type} consumer(s)...')
        )
        
        threads = []
        
        try:
            if consumer_type in ['initiate', 'all']:
                self.stdout.write('Starting call initiation consumer...')
                thread = start_initiated_call_consumer()
                threads.append(thread)
            
            if consumer_type in ['callback', 'all']:
                self.stdout.write('Starting callback consumer...')
                thread = start_callback_consumer()
                threads.append(thread)
            
            self.stdout.write(
                self.style.SUCCESS('Consumers started successfully')
            )
            
            # Keep the main thread alive
            try:
                while True:
                    time.sleep(1)
                    # Check if any thread has died
                    for thread in threads:
                        if not thread.is_alive():
                            self.stdout.write(
                                self.style.ERROR('A consumer thread has died')
                            )
                            break
            except KeyboardInterrupt:
                self.stdout.write(
                    self.style.WARNING('Stopping consumers...')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Consumer error: {str(e)}')
            )
            logger.error(f'Consumer error: {str(e)}')
        finally:
            stop_consumers()
            self.stdout.write(
                self.style.SUCCESS('Consumers stopped')
            )
