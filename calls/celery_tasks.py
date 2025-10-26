"""
Celery Periodic Tasks

This module contains Celery Beat tasks for scheduled operations.
These tasks run periodically (like cron jobs) using Celery Beat scheduler.
"""

import logging
import yaml
from datetime import datetime, timedelta
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from .models import CallLog, Campaign
from .tasks import process_call_initiation
from .utils import ConcurrencyManager, MetricsManager
from config import Config

logger = logging.getLogger(__name__)


@shared_task(name='calls.celery_tasks.process_retry_calls')
def process_retry_calls():
    """
    Periodic task to process calls eligible for retry.
    
    This task runs every minute (configured in Celery Beat schedule).
    It finds calls with status DISCONNECTED or RNR that are eligible for retry
    and triggers the call initiation task for each one.
    
    Returns:
        dict: Statistics about processed retries
    """
    try:
        logger.info("[Celery Beat] Starting retry processing task")
        
        # Load retry configuration
        config = load_retry_config()
        if not config:
            logger.error("[Celery Beat] Failed to load retry configuration")
            return {'success': False, 'error': 'Config load failed'}
        
        now = timezone.now()
        retry_count = 0
        max_concurrent_retries = config.get('scheduler', {}).get('max_concurrent_retries', 50)
        
        # Get calls that are eligible for retry
        eligible_calls = CallLog.objects.filter(
            status__in=['DISCONNECTED', 'RNR'],
            next_retry_at__lte=now,
            attempt_count__lt=Config.MAX_RETRY_ATTEMPTS
        ).select_related('campaign')[:config.get('scheduler', {}).get('batch_size', 100)]
        
        logger.info(f"[Celery Beat] Found {len(eligible_calls)} eligible calls for retry")
        
        for call_log in eligible_calls:
            if retry_count >= max_concurrent_retries:
                logger.info(f"[Celery Beat] Reached max concurrent retries ({max_concurrent_retries})")
                break
            
            try:
                # Get retry rules for this campaign
                retry_rules = get_retry_rules_for_campaign(call_log.campaign.id, config)
                
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
                            logger.info(
                                f"[Celery Beat] Queued retry for {call_log.call_id} "
                                f"(attempt {call_log.attempt_count})"
                            )
                    else:
                        logger.debug(f"[Celery Beat] Cannot retry call {call_log.call_id}: {reason}")
                else:
                    # Not in retry window, calculate next retry time
                    next_retry_time, next_rule = calculate_next_retry_time(
                        call_log, retry_rules, config
                    )
                    if call_log.next_retry_at != next_retry_time:
                        call_log.next_retry_at = next_retry_time
                        call_log.save()
                        logger.debug(
                            f"[Celery Beat] Updated next retry time for {call_log.call_id}: "
                            f"{next_retry_time}"
                        )
            
            except Exception as e:
                logger.error(f"[Celery Beat] Error processing retry for call {call_log.call_id}: {str(e)}")
        
        if retry_count > 0:
            logger.info(f"[Celery Beat] Processed {retry_count} retry attempts")
        
        return {
            'success': True,
            'retries_processed': retry_count,
            'eligible_calls': len(eligible_calls)
        }
        
    except Exception as e:
        logger.error(f"[Celery Beat] Error in retry processing task: {str(e)}")
        return {'success': False, 'error': str(e)}


def load_retry_config():
    """Load retry configuration from YAML file"""
    try:
        with open(Config.RETRY_SCHEDULE_CONFIG_PATH, 'r') as file:
            config = yaml.safe_load(file)
        return config
    except Exception as e:
        logger.error(f"Error loading retry config: {str(e)}")
        return None


def get_retry_rules_for_campaign(campaign_id, config):
    """Get retry rules for a specific campaign"""
    if not config:
        return []
    
    # Check for campaign-specific rules
    campaign_rules = config.get('campaign_rules', [])
    for rule_set in campaign_rules:
        if rule_set.get('campaign_id') == campaign_id:
            return rule_set.get('rules', [])
    
    # Return global rules if no campaign-specific rules found
    return config.get('global_rules', [])


def is_in_retry_window(now, retry_rules):
    """
    Check if current time is within a retry window
    
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
                start_time = datetime.strptime(slot['start_time'], '%H:%M').time()
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


@shared_task(name='calls.celery_tasks.cleanup_old_calls')
def cleanup_old_calls():
    """
    Periodic task to cleanup old completed/failed calls
    
    This task runs daily to clean up old call records
    that are no longer needed.
    """
    try:
        logger.info("[Celery Beat] Starting cleanup task")
        
        # Delete calls older than 30 days that are completed or failed
        cutoff_date = timezone.now() - timedelta(days=30)
        
        deleted_count = CallLog.objects.filter(
            status__in=['COMPLETED', 'FAILED'],
            updated_at__lt=cutoff_date
        ).delete()[0]
        
        logger.info(f"[Celery Beat] Cleaned up {deleted_count} old call records")
        
        return {'success': True, 'deleted_count': deleted_count}
        
    except Exception as e:
        logger.error(f"[Celery Beat] Error in cleanup task: {str(e)}")
        return {'success': False, 'error': str(e)}
