"""
Unified command to start all services: Django server, Consumers, and Scheduler
This is the recommended way to run the complete system for testing all features
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command
import subprocess
import threading
import logging
import time
import os
import signal
import sys

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Start all services: Django server, Kafka consumers, and retry scheduler'

    def add_arguments(self, parser):
        parser.add_argument(
            '--host',
            type=str,
            default='0.0.0.0',
            help='Django server host (default: 0.0.0.0)'
        )
        parser.add_argument(
            '--port',
            type=int,
            default=8000,
            help='Django server port (default: 8000)'
        )
        parser.add_argument(
            '--no-mock',
            action='store_true',
            help='Do not start mock external service'
        )

    def __init__(self):
        super().__init__()
        self.processes = []
        self.threads = []

    def handle(self, *args, **options):
        host = options['host']
        port = options['port']
        start_mock = not options['no_mock']
        
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('🚀 Starting Campaign Call Manager System'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        
        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # 1. Start Mock External Service (if enabled)
            if start_mock:
                self.start_mock_service()
                time.sleep(2)  # Wait for mock service to start
            
            # 2. Start Kafka Consumers
            self.start_consumers()
            time.sleep(2)  # Wait for consumers to initialize
            
            # 3. Start Retry Scheduler
            self.start_scheduler()
            time.sleep(2)  # Wait for scheduler to initialize
            
            # 4. Start Django Server (last, so it's ready to accept requests)
            self.start_django_server(host, port)
            
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=' * 70))
            self.stdout.write(self.style.SUCCESS('✅ All services started successfully!'))
            self.stdout.write(self.style.SUCCESS('=' * 70))
            self.stdout.write('')
            self.print_service_status(host, port, start_mock)
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Press Ctrl+C to stop all services'))
            self.stdout.write('')
            
            # Keep main thread alive
            while True:
                time.sleep(1)
                # Check if any critical thread has died
                for thread in self.threads:
                    if not thread.is_alive():
                        self.stdout.write(
                            self.style.ERROR('⚠️  A service thread has died! Shutting down...')
                        )
                        self.shutdown_all_services()
                        sys.exit(1)
                        
        except KeyboardInterrupt:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('🛑 Shutdown initiated by user'))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error: {str(e)}')
            )
            logger.error(f'Error in start_all: {str(e)}')
        finally:
            self.shutdown_all_services()

    def start_mock_service(self):
        """Start mock external service"""
        self.stdout.write('📞 Starting Mock External Service...')
        try:
            process = subprocess.Popen(
                ['python', 'mock_service.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd()
            )
            self.processes.append(('Mock Service', process))
            self.stdout.write(self.style.SUCCESS('   ✅ Mock service started on port 8001'))
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'   ❌ Failed to start mock service: {str(e)}')
            )

    def start_consumers(self):
        """Start Kafka consumers in a thread"""
        self.stdout.write('🎧 Starting Kafka Consumers...')
        
        def run_consumers():
            try:
                call_command('run_consumers')
            except Exception as e:
                logger.error(f'Consumer error: {str(e)}')
        
        thread = threading.Thread(target=run_consumers, daemon=True, name='Consumers')
        thread.start()
        self.threads.append(thread)
        self.stdout.write(self.style.SUCCESS('   ✅ Kafka consumers started'))

    def start_scheduler(self):
        """Start retry scheduler in a thread"""
        self.stdout.write('⏰ Starting Retry Scheduler...')
        
        def run_scheduler():
            try:
                call_command('run_scheduler')
            except Exception as e:
                logger.error(f'Scheduler error: {str(e)}')
        
        thread = threading.Thread(target=run_scheduler, daemon=True, name='Scheduler')
        thread.start()
        self.threads.append(thread)
        self.stdout.write(self.style.SUCCESS('   ✅ Retry scheduler started'))

    def start_django_server(self, host, port):
        """Start Django development server in a thread"""
        self.stdout.write(f'🌐 Starting Django Server on {host}:{port}...')
        
        def run_server():
            try:
                call_command('runserver', f'{host}:{port}', '--noreload')
            except Exception as e:
                logger.error(f'Server error: {str(e)}')
        
        thread = threading.Thread(target=run_server, daemon=True, name='DjangoServer')
        thread.start()
        self.threads.append(thread)
        time.sleep(3)  # Wait for server to start
        self.stdout.write(self.style.SUCCESS(f'   ✅ Django server started'))

    def print_service_status(self, host, port, mock_enabled):
        """Print status of all services"""
        self.stdout.write(self.style.SUCCESS('📊 Service Status:'))
        self.stdout.write('')
        self.stdout.write(f'   🌐 Django API Server:    http://{host}:{port}')
        self.stdout.write(f'   🎧 Kafka Consumers:      Running (2 consumers)')
        self.stdout.write(f'   ⏰ Retry Scheduler:      Running')
        if mock_enabled:
            self.stdout.write(f'   📞 Mock Service:         http://localhost:8001')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('🧪 Test Endpoints:'))
        self.stdout.write('')
        self.stdout.write(f'   • Metrics:     http://{host}:{port}/api/v1/metrics/')
        self.stdout.write(f'   • Campaigns:   http://{host}:{port}/api/v1/campaigns/')
        self.stdout.write(f'   • Init Call:   http://{host}:{port}/api/v1/initiate-call/')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🔑 Authentication:'))
        self.stdout.write('   Add header: X-Auth-Token: dev-token-12345')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('📝 Logs:'))
        self.stdout.write('   • Application:  tail -f logs/app.log')
        self.stdout.write('   • API:          tail -f logs/api.log')
        self.stdout.write('   • Calls:        tail -f logs/calls.log')
        self.stdout.write('   • Kafka:        tail -f logs/kafka.log')
        self.stdout.write('   • Errors:       tail -f logs/error.log')

    def shutdown_all_services(self):
        """Gracefully shutdown all services"""
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🛑 Shutting down all services...'))
        
        # Stop processes
        for name, process in self.processes:
            try:
                self.stdout.write(f'   Stopping {name}...')
                process.terminate()
                process.wait(timeout=5)
            except Exception as e:
                self.stdout.write(f'   ⚠️  Error stopping {name}: {str(e)}')
                try:
                    process.kill()
                except:
                    pass
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('✅ All services stopped'))

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🛑 Received shutdown signal'))
        self.shutdown_all_services()
        sys.exit(0)
