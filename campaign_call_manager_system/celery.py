"""
Celery configuration for Campaign Call Manager System

This module configures Celery for asynchronous task processing.
Tasks are executed by Celery workers running in the background.
"""

import os
from celery import Celery
from celery.signals import setup_logging

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campaign_call_manager_system.settings')

app = Celery('campaign_call_manager')

# Load task modules from all registered Django app configs.
# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Explicitly import periodic tasks so they get registered
app.autodiscover_tasks(['calls'], related_name='periodic_tasks')


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """Configure Celery to use Django's logging configuration"""
    from logging.config import dictConfig
    from django.conf import settings
    dictConfig(settings.LOGGING)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to test Celery is working"""
    print(f'Request: {self.request!r}')
