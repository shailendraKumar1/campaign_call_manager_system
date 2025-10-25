import logging
from datetime import datetime, timedelta
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction
from .models import ConcurrencyControl, CallMetrics
from config import Config
import uuid

logger = logging.getLogger(__name__)


class ConcurrencyManager:
    """Manages call concurrency using Redis cache"""
    
    @staticmethod
    def can_initiate_call(phone_number, campaign_id):
        """Check if a call can be initiated based on concurrency and duplicate rules"""
        
        # Check if we're at max concurrent calls
        current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
        if current_count >= Config.MAX_CONCURRENT_CALLS:
            logger.warning(f"Max concurrent calls reached: {current_count}")
            return False, "Maximum concurrent calls limit reached"
        
        # Check for duplicate calls to same number
        duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
        if cache.get(duplicate_key):
            logger.warning(f"Duplicate call prevention: {phone_number}")
            return False, "Call to this number already in progress"
        
        return True, "OK"
    
    @staticmethod
    def start_call(call_id, phone_number, campaign_id):
        """Mark a call as started in concurrency control"""
        try:
            with transaction.atomic():
                # Increment concurrent calls counter
                current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
                cache.set(Config.REDIS_CONCURRENCY_KEY, current_count + 1, timeout=3600)
                
                # Set duplicate prevention lock
                duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                cache.set(duplicate_key, call_id, timeout=Config.DUPLICATE_CALL_WINDOW_MINUTES * 60)
                
                # Track in database for persistence
                ConcurrencyControl.objects.create(
                    call_id=call_id,
                    phone_number=phone_number,
                    campaign_id=campaign_id
                )
                
                logger.info(f"Call started: {call_id}, concurrent count: {current_count + 1}")
                return True
                
        except Exception as e:
            logger.error(f"Error starting call {call_id}: {str(e)}")
            return False
    
    @staticmethod
    def end_call(call_id, phone_number):
        """Mark a call as ended in concurrency control"""
        try:
            with transaction.atomic():
                # Decrement concurrent calls counter
                current_count = cache.get(Config.REDIS_CONCURRENCY_KEY, 0)
                if current_count > 0:
                    cache.set(Config.REDIS_CONCURRENCY_KEY, current_count - 1, timeout=3600)
                
                # Remove duplicate prevention lock
                duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                cache.delete(duplicate_key)
                
                # Remove from database tracking
                ConcurrencyControl.objects.filter(call_id=call_id).delete()
                
                logger.info(f"Call ended: {call_id}, concurrent count: {max(0, current_count - 1)}")
                return True
                
        except Exception as e:
            logger.error(f"Error ending call {call_id}: {str(e)}")
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
    """Generate a unique call ID"""
    timestamp = int(timezone.now().timestamp())
    unique_id = str(uuid.uuid4())[:8]
    return f"call_{campaign_id}_{phone_number}_{timestamp}_{unique_id}"


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
