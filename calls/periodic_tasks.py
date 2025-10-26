"""
Celery Beat Periodic Tasks

This module contains periodic tasks that run on a schedule using Celery Beat.
These replace the Python schedule-based scheduler.
"""

import logging
import yaml
from datetime import datetime, timedelta
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from .models import CallLog
from .tasks import process_call_initiation
from .utils import ConcurrencyManager, MetricsManager
from config import Config

logger = logging.getLogger(__name__)


@shared_task(name='calls.periodic_tasks.process_retry_calls')
def process_retry_calls():
    """Process calls eligible for retry"""
    try:
        config = load_retry_config()
        if not config:
            logger.error("Failed to load retry configuration")
            return {'success': False, 'error': 'Config load failed'}
        
        now = timezone.now()
        retry_count = 0
        max_concurrent_retries = config.get('scheduler', {}).get('max_concurrent_retries', 50)
        batch_size = config.get('scheduler', {}).get('batch_size', 100)
        
        eligible_calls = CallLog.objects.filter(
            status__in=['DISCONNECTED', 'RNR'],
            next_retry_at__lte=now,
            attempt_count__lt=Config.MAX_RETRY_ATTEMPTS
        ).select_related('campaign')[:batch_size]
        
        if not eligible_calls:
            return {'success': True, 'retries_processed': 0}
        
        logger.info(f"Processing {len(eligible_calls)} retry calls")
        
        for call_log in eligible_calls:
            if retry_count >= max_concurrent_retries:
                logger.info(f"[Celery Beat] Reached max concurrent retries ({max_concurrent_retries})")
                break
            
            try:
                # Get global retry rules
                retry_rules = config.get('global_rules', [])
                
                # Check if we're in a retry window
                in_window, current_rule = is_in_retry_window(now, retry_rules)
                
                if in_window:
                    # Check concurrency limits
                    can_retry, reason = ConcurrencyManager.can_initiate_call(
                        call_log.phone_number, 
                        call_log.campaign.id
                    )
                    
                    if can_retry:
                        with transaction.atomic():
                            # Update call log for retry
                            call_log.attempt_count += 1
                            call_log.status = 'RETRYING'
                            call_log.last_attempt_at = now
                            
                            # Calculate next retry time
                            next_retry_time, next_rule = calculate_next_retry_time(
                                call_log, retry_rules, config
                            )
                            call_log.next_retry_at = next_retry_time
                            
                            # Update max attempts based on current rule
                            if current_rule:
                                call_log.max_attempts = current_rule['max_attempts']
                            
                            call_log.save()
                            
                            # Start concurrency tracking
                            ConcurrencyManager.start_call(
                                call_log.call_id, 
                                call_log.phone_number, 
                                call_log.campaign.id
                            )
                            
                            # Trigger retry via Celery task
                            process_call_initiation.delay(
                                call_log.call_id,
                                call_log.phone_number,
                                call_log.campaign.id
                            )
                            
                            # Update metrics
                            MetricsManager.increment_call_status_count('RETRYING')
                            
                            retry_count += 1
                            logger.info(f"Queued retry: {call_log.call_id} (attempt {call_log.attempt_count}/{call_log.max_attempts})")
                else:
                    # Not in retry window
                    next_retry_time, next_rule = calculate_next_retry_time(
                        call_log, retry_rules, config
                    )
                    if call_log.next_retry_at != next_retry_time:
                        call_log.next_retry_at = next_retry_time
                        call_log.save()
            
            except Exception as e:
                logger.error(f"Error processing retry: {str(e)}")
        
        logger.info(f"Processed {retry_count} retry attempts")
        
        return {
            'success': True,
            'retries_processed': retry_count,
            'eligible_calls': len(eligible_calls)
        }
        
    except Exception as e:
        logger.error(f"Error in retry processing: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}


def load_retry_config():
    """Load retry configuration from YAML file"""
    try:
        with open(Config.RETRY_SCHEDULE_CONFIG_PATH, 'r') as file:
            config = yaml.safe_load(file)
        return config
    except Exception as e:
        logger.error(f"[Celery Beat] Error loading retry config: {str(e)}")
        return None


def is_in_retry_window(now, retry_rules):
    """
    Check if current time is within a retry window
    
    Args:
        now: Current datetime
        retry_rules: List of retry rules
        
    Returns:
        tuple: (in_window: bool, current_rule: dict or None)
    """
    current_day = now.strftime('%A').lower()
    current_time = now.time()
    
    for rule in retry_rules:
        rule_days = [day.lower() for day in rule.get('days', [])]
        
        if current_day in rule_days:
            time_slots = rule.get('time_slots', [])
            
            for slot in time_slots:
                start_time = datetime.strptime(slot['start_time'], '%H:%M').time()
                end_time = datetime.strptime(slot['end_time'], '%H:%M').time()
                
                if start_time <= current_time <= end_time:
                    return True, slot
    
    return False, None


def calculate_next_retry_time(call_log, retry_rules, config):
    """
    Calculate the next retry time based on retry rules
    
    Args:
        call_log: CallLog instance
        retry_rules: List of retry rules
        config: Retry configuration dict
        
    Returns:
        tuple: (next_retry_time: datetime, next_rule: dict or None)
    """
    now = timezone.now()
    current_day = now.strftime('%A').lower()
    
    # Find the next available time slot
    for rule in retry_rules:
        rule_days = [day.lower() for day in rule.get('days', [])]
        
        if current_day in rule_days:
            time_slots = rule.get('time_slots', [])
            
            for slot in time_slots:
                retry_interval = slot.get('retry_interval_minutes', 60)
                
                # Calculate next retry time
                next_retry = now + timedelta(minutes=retry_interval)
                
                # Check if next retry is within today's slot
                end_time = datetime.strptime(slot['end_time'], '%H:%M').time()
                if next_retry.time() <= end_time:
                    return next_retry, slot
    
    # If no slot found for today, use default
    default_interval = config.get('defaults', {}).get('retry_interval_minutes', 60)
    return now + timedelta(minutes=default_interval), None


@shared_task(name='calls.periodic_tasks.cleanup_old_metrics')
def cleanup_old_metrics():
    """
    Celery Beat task to cleanup old metrics data.
    Runs daily to keep database clean.
    """
    try:
        from .models import CallMetrics
        
        logger.info("[Celery Beat] Starting metrics cleanup")
        
        # Delete metrics older than 90 days
        cutoff_date = timezone.now().date() - timedelta(days=90)
        
        deleted_count = CallMetrics.objects.filter(
            date__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"[Celery Beat] Cleaned up {deleted_count} old metric records")
        
        return {'success': True, 'deleted_count': deleted_count}
        
    except Exception as e:
        logger.error(f"[Celery Beat] Error in metrics cleanup: {str(e)}")
        return {'success': False, 'error': str(e)}


@shared_task(name='calls.periodic_tasks.process_call_queues')
def process_call_queues():
    """
    Celery Beat task to process call queues for all campaigns.
    Runs every minute as a fallback to ensure queues are always processed.
    """
    try:
        from .models import Campaign
        from .utils import CallQueueManager
        from .tasks import process_queue_batch
        
        logger.info("[Celery Beat] Checking call queues")
        
        # Get all active campaigns
        active_campaigns = Campaign.objects.filter(is_active=True)
        
        processed_campaigns = 0
        
        for campaign in active_campaigns:
            # Check if campaign has queued calls
            queue_size = CallQueueManager.get_queue_size(campaign.id)
            
            if queue_size > 0:
                logger.info(f"[Celery Beat] Campaign {campaign.id} has {queue_size} queued calls")
                # Trigger queue processor
                process_queue_batch.delay(campaign.id)
                processed_campaigns += 1
        
        logger.info(f"[Celery Beat] Triggered queue processing for {processed_campaigns} campaigns")
        
        return {
            'success': True,
            'campaigns_processed': processed_campaigns
        }
        
    except Exception as e:
        logger.error(f"[Celery Beat] Error processing call queues: {str(e)}")
        return {'success': False, 'error': str(e)}
