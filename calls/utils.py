import logging
import json
from datetime import datetime, timedelta
from enum import Enum
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from .models import ConcurrencyControl, CallMetrics
from config import Config
import uuid
import redis

logger = logging.getLogger(__name__)

class CallValidationResult(Enum):
    """Enum for call validation results"""
    OK = "OK"
    CAPACITY_LIMIT_REACHED = "CAPACITY_LIMIT_REACHED"
    DUPLICATE_CALL_IN_PROGRESS = "DUPLICATE_CALL_IN_PROGRESS"

# Redis client for queue operations
redis_client = redis.from_url(Config.REDIS_URL, decode_responses=True)


class ConcurrencyManager:
    """Manages call concurrency using Redis cache"""
    
    @staticmethod
    def can_initiate_call(phone_number, campaign_id):
        """
        Check if call can be initiated
        
        Returns:
            tuple: (can_initiate: bool, result: CallValidationResult)
        """
        
        # Check max concurrent calls
        current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
        
        if current_count >= Config.MAX_CONCURRENT_CALLS:
            return False, CallValidationResult.CAPACITY_LIMIT_REACHED
        
        # Check duplicate calls
        duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
        existing_call_id = cache.get(duplicate_key)
        
        if existing_call_id:
            return False, CallValidationResult.DUPLICATE_CALL_IN_PROGRESS
        
        return True, CallValidationResult.OK
    
    @staticmethod
    def get_available_slots():
        """Get number of available concurrency slots"""
        current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
        return max(0, Config.MAX_CONCURRENT_CALLS - current_count)
    
    @staticmethod
    def start_call(call_id, phone_number, campaign_id):
        """Start call tracking"""
        try:
            with transaction.atomic():
                current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
                cache.set(Config.REDIS_CONCURRENCY_KEY, current_count + 1, timeout=3600)
                
                duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                cache.set(duplicate_key, call_id, timeout=Config.DUPLICATE_CALL_WINDOW_MINUTES * 60)
                
                ConcurrencyControl.objects.create(
                    call_id=call_id,
                    phone_number=phone_number,
                    campaign_id=campaign_id
                )
                
                logger.info(f"Call tracking started: {call_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error starting call tracking: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def end_call(call_id, phone_number):
        """End call tracking"""
        try:
            with transaction.atomic():
                current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
                if current_count > 0:
                    cache.set(Config.REDIS_CONCURRENCY_KEY, current_count - 1, timeout=3600)
                
                duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                cache.delete(duplicate_key)
                
                ConcurrencyControl.objects.filter(call_id=call_id).delete()
                
                logger.info(f"Call tracking ended: {call_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error ending call tracking: {str(e)}", exc_info=True)
            return False
    
    @staticmethod
    def get_current_concurrent_count():
        """Get current number of concurrent calls"""
        return cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
    
    @staticmethod
    def cleanup_stale_calls():
        """Clean up stale concurrency control entries"""
        try:
            # Remove entries older than 1 hour (assuming max call duration)
            cutoff_time = timezone.now() - timedelta(hours=1)
            stale_calls = ConcurrencyControl.objects.filter(started_at__lt=cutoff_time)
            
            for call in stale_calls:
                ConcurrencyManager.end_call(call.call_id, call.phone_number)
            
            logger.info(f"Cleaned up {stale_calls.count()} stale calls")
            
        except Exception as e:
            logger.error(f"Error cleaning up stale calls: {str(e)}")


class MetricsManager:
    """Manages call metrics and observability"""
    
    @staticmethod
    def update_daily_metrics(date=None, **kwargs):
        """Update daily metrics with provided values"""
        if date is None:
            date = timezone.now().date()
        
        try:
            metrics, created = CallMetrics.objects.get_or_create(
                date=date,
                defaults={
                    'total_calls_initiated': 0,
                    'total_calls_picked': 0,
                    'total_calls_disconnected': 0,
                    'total_calls_rnr': 0,
                    'total_calls_failed': 0,
                    'total_retries': 0,
                    'peak_concurrent_calls': 0,
                    'total_call_duration_seconds': 0,
                    'dlq_entries_created': 0,
                }
            )
            
            # Update metrics with provided values
            for key, value in kwargs.items():
                if hasattr(metrics, key):
                    current_value = getattr(metrics, key)
                    if key == 'peak_concurrent_calls':
                        # For peak values, take the maximum
                        setattr(metrics, key, max(current_value, value))
                    else:
                        # For counters, add the value
                        setattr(metrics, key, current_value + value)
            
            metrics.save()
            logger.info(f"Updated metrics for {date}: {kwargs}")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {str(e)}")
    
    @staticmethod
    def increment_call_status_count(status, call_duration=None):
        """Increment counter for specific call status"""
        today = timezone.now().date()
        
        status_mapping = {
            'INITIATED': 'total_calls_initiated',
            'PICKED': 'total_calls_picked',
            'DISCONNECTED': 'total_calls_disconnected',
            'RNR': 'total_calls_rnr',
            'FAILED': 'total_calls_failed',
            'RETRYING': 'total_retries',
        }
        
        updates = {}
        if status in status_mapping:
            updates[status_mapping[status]] = 1
        
        if call_duration:
            updates['total_call_duration_seconds'] = call_duration
        
        # Update peak concurrent calls
        current_concurrent = ConcurrencyManager.get_current_concurrent_count()
        updates['peak_concurrent_calls'] = current_concurrent
        
        MetricsManager.update_daily_metrics(date=today, **updates)


def generate_call_id(campaign_id, phone_number):
    """Generate a unique call ID using UUID"""
    return str(uuid.uuid4())


def is_valid_phone_number(phone_number):
    """Basic phone number validation"""
    if not phone_number:
        return False
    
    # Remove common formatting characters
    cleaned = phone_number.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
    
    # Check if it's all digits and reasonable length
    return cleaned.isdigit() and 7 <= len(cleaned) <= 15


def is_time_in_window(current, start, end):
    """ Returns True if current time is within [start, end] window. """
    return start <= current <= end


class CallQueueManager:
    """
    Redis-based call queue manager
    
    Manages a Redis list as a FIFO queue for pending calls.
    Automatically processes calls as concurrency slots become available.
    """
    
    QUEUE_KEY_PREFIX = "call_queue:"
    
    @staticmethod
    def add_to_queue(campaign_id, phone_numbers, priority=0):
        """
        Add phone numbers to Redis queue
        
        Args:
            campaign_id: Campaign ID
            phone_numbers: List of phone numbers
            priority: Priority level (higher = processed first)
            
        Returns:
            dict: Status of queued calls
        """
        try:
            queue_key = f"{CallQueueManager.QUEUE_KEY_PREFIX}{campaign_id}"
            queued_count = 0
            
            for phone_number in phone_numbers:
                # Create queue entry
                entry = {
                    'campaign_id': campaign_id,
                    'phone_number': phone_number,
                    'priority': priority,
                    'queued_at': timezone.now().isoformat()
                }
                
                # Push to Redis list (RPUSH = add to end of list)
                redis_client.rpush(queue_key, json.dumps(entry))
                queued_count += 1
            
            logger.info(f"[Queue Manager] Added {queued_count} calls to queue for campaign {campaign_id}")
            
            return {
                'success': True,
                'queued_count': queued_count,
                'queue_key': queue_key
            }
            
        except Exception as e:
            logger.error(f"[Queue Manager] Error adding to queue: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_queue_size(campaign_id):
        """Get number of pending calls in queue"""
        try:
            queue_key = f"{CallQueueManager.QUEUE_KEY_PREFIX}{campaign_id}"
            return redis_client.llen(queue_key)
        except Exception as e:
            logger.error(f"[Queue Manager] Error getting queue size: {str(e)}")
            return 0
    
    @staticmethod
    def pop_from_queue(campaign_id, count=1):
        """
        Pop calls from queue (FIFO)
        
        Args:
            campaign_id: Campaign ID
            count: Number of calls to pop
            
        Returns:
            list: List of queue entries
        """
        try:
            queue_key = f"{CallQueueManager.QUEUE_KEY_PREFIX}{campaign_id}"
            entries = []
            
            for _ in range(count):
                # LPOP = pop from beginning of list (FIFO)
                entry_json = redis_client.lpop(queue_key)
                if entry_json:
                    entry = json.loads(entry_json)
                    entries.append(entry)
                else:
                    break
            
            return entries
            
        except Exception as e:
            logger.error(f"[Queue Manager] Error popping from queue: {str(e)}")
            return []
    
    @staticmethod
    def clear_queue(campaign_id):
        """Clear all pending calls from queue"""
        try:
            queue_key = f"{CallQueueManager.QUEUE_KEY_PREFIX}{campaign_id}"
            redis_client.delete(queue_key)
            logger.info(f"[Queue Manager] Cleared queue for campaign {campaign_id}")
            return True
        except Exception as e:
            logger.error(f"[Queue Manager] Error clearing queue: {str(e)}")
            return False
