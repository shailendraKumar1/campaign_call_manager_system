import yaml
import logging
import schedule
import time
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from .models import CallLog, RetryRule, Campaign
from .publisher import publish_retry_event
from .utils import ConcurrencyManager, MetricsManager
from .consumer import DLQProcessor
from config import Config

logger = logging.getLogger(__name__)


class RetryScheduler:
    """Advanced retry scheduler with YAML-based configuration"""
    
    def __init__(self):
        self.config = None
        self.running = False
        self.load_config()
    
    def load_config(self):
        """Load retry configuration from YAML file"""
        try:
            with open(Config.RETRY_SCHEDULE_CONFIG_PATH, 'r') as file:
                self.config = yaml.safe_load(file)
            logger.info(f"Loaded retry configuration from {Config.RETRY_SCHEDULE_CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Error loading retry config: {str(e)}")
            # Use default configuration
            self.config = {
                'defaults': {
                    'max_attempts': 3,
                    'retry_interval_minutes': 60,
                    'concurrent_call_limit': 100
                },
                'global_rules': [],
                'campaign_rules': []
            }
    
    def get_retry_rules_for_campaign(self, campaign_id=None):
        """Get retry rules for a specific campaign or global rules"""
        rules = []
        
        # Add global rules
        for global_rule in self.config.get('global_rules', []):
            for day_rule in global_rule.get('days', []):
                for time_slot in global_rule.get('time_slots', []):
                    rules.append({
                        'name': global_rule.get('name', 'Global Rule'),
                        'day': day_rule,
                        'start_time': time_slot.get('start_time'),
                        'end_time': time_slot.get('end_time'),
                        'max_attempts': time_slot.get('max_attempts', 3),
                        'retry_interval_minutes': time_slot.get('retry_interval_minutes', 60),
                        'campaign_id': None
                    })
        
        # Add campaign-specific rules if campaign_id is provided
        if campaign_id:
            for campaign_rule in self.config.get('campaign_rules', []):
                if campaign_rule.get('campaign_id') == campaign_id:
                    for rule in campaign_rule.get('rules', []):
                        for day_rule in rule.get('days', []):
                            for time_slot in rule.get('time_slots', []):
                                rules.append({
                                    'name': rule.get('name', 'Campaign Rule'),
                                    'day': day_rule,
                                    'start_time': time_slot.get('start_time'),
                                    'end_time': time_slot.get('end_time'),
                                    'max_attempts': time_slot.get('max_attempts', 3),
                                    'retry_interval_minutes': time_slot.get('retry_interval_minutes', 60),
                                    'campaign_id': campaign_id
                                })
        
        return rules
    
    def is_in_retry_window(self, current_time, retry_rules):
        """Check if current time is within any retry window"""
        current_day = current_time.strftime('%A').lower()
        current_time_str = current_time.strftime('%H:%M')
        
        for rule in retry_rules:
            if rule['day'] == current_day:
                start_time = rule['start_time']
                end_time = rule['end_time']
                
                if start_time <= current_time_str <= end_time:
                    return True, rule
        
        return False, None
    
    def calculate_next_retry_time(self, call_log, retry_rules):
        """Calculate the next retry time based on retry rules"""
        now = timezone.now()
        
        # Find the next available retry window
        for days_ahead in range(7):  # Look up to 7 days ahead
            check_date = now + timedelta(days=days_ahead)
            check_day = check_date.strftime('%A').lower()
            
            for rule in retry_rules:
                if rule['day'] == check_day:
                    start_time_str = rule['start_time']
                    start_hour, start_minute = map(int, start_time_str.split(':'))
                    
                    retry_time = check_date.replace(
                        hour=start_hour,
                        minute=start_minute,
                        second=0,
                        microsecond=0
                    )
                    
                    # If it's today, make sure the time is in the future
                    if days_ahead == 0 and retry_time <= now:
                        continue
                    
                    return retry_time, rule
        
        # If no retry window found, use default interval
        default_interval = self.config.get('defaults', {}).get('retry_interval_minutes', 60)
        return now + timedelta(minutes=default_interval), None
    
    def retry_failed_calls(self):
        """Process calls that are eligible for retry"""
        try:
            now = timezone.now()
            
            # Get calls that are eligible for retry
            eligible_calls = CallLog.objects.filter(
                status__in=['DISCONNECTED', 'RNR'],
                next_retry_at__lte=now,
                attempt_count__lt=Config.MAX_RETRY_ATTEMPTS
            ).select_related('campaign')[:self.config.get('scheduler', {}).get('batch_size', 100)]
            
            retry_count = 0
            max_concurrent_retries = self.config.get('scheduler', {}).get('max_concurrent_retries', 50)
            
            for call_log in eligible_calls:
                if retry_count >= max_concurrent_retries:
                    break
                
                try:
                    # Get retry rules for this campaign
                    retry_rules = self.get_retry_rules_for_campaign(call_log.campaign.id)
                    
                    # Check if we're in a retry window
                    in_window, current_rule = self.is_in_retry_window(now, retry_rules)
                    
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
                                next_retry_time, next_rule = self.calculate_next_retry_time(call_log, retry_rules)
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
                                
                                # Publish retry event
                                publish_retry_event(call_log)
                                
                                # Update metrics
                                MetricsManager.increment_call_status_count('RETRYING')
                                
                                retry_count += 1
                                logger.info(f"Retrying call {call_log.call_id} (attempt {call_log.attempt_count})")
                        else:
                            logger.debug(f"Cannot retry call {call_log.call_id}: {reason}")
                    else:
                        # Not in retry window, calculate next retry time
                        next_retry_time, next_rule = self.calculate_next_retry_time(call_log, retry_rules)
                        if call_log.next_retry_at != next_retry_time:
                            call_log.next_retry_at = next_retry_time
                            call_log.save()
                            logger.debug(f"Updated next retry time for {call_log.call_id}: {next_retry_time}")
                
                except Exception as e:
                    logger.error(f"Error processing retry for call {call_log.call_id}: {str(e)}")
            
            if retry_count > 0:
                logger.info(f"Processed {retry_count} retry attempts")
            
        except Exception as e:
            logger.error(f"Error in retry_failed_calls: {str(e)}")
    
    def cleanup_expired_calls(self):
        """Mark calls as failed if they've exceeded max attempts"""
        try:
            expired_calls = CallLog.objects.filter(
                status__in=['DISCONNECTED', 'RNR', 'RETRYING'],
                attempt_count__gte=Config.MAX_RETRY_ATTEMPTS
            )
            
            count = 0
            for call_log in expired_calls:
                call_log.status = 'FAILED'
                call_log.error_message = f'Max retry attempts reached ({call_log.attempt_count})'
                call_log.updated_at = timezone.now()
                call_log.save()
                
                # End concurrency tracking
                ConcurrencyManager.end_call(call_log.call_id, call_log.phone_number)
                count += 1
            
            if count > 0:
                logger.info(f"Marked {count} calls as failed due to max retry attempts")
            
        except Exception as e:
            logger.error(f"Error cleaning up expired calls: {str(e)}")
    
    def cleanup_stale_resources(self):
        """Clean up stale resources"""
        try:
            # Clean up stale concurrency control entries
            ConcurrencyManager.cleanup_stale_calls()
            
            # Process DLQ entries
            DLQProcessor.process_dlq_entries()
            
            # Clean up old DLQ entries
            DLQProcessor.cleanup_old_dlq_entries()
            
        except Exception as e:
            logger.error(f"Error cleaning up stale resources: {str(e)}")
    
    def run_scheduler(self):
        """Run the scheduler with all periodic tasks"""
        if not Config.SCHEDULER_ENABLED:
            logger.info("Scheduler is disabled")
            return
        
        self.running = True
        interval_minutes = Config.SCHEDULER_INTERVAL_MINUTES
        
        # Schedule periodic tasks
        schedule.every(interval_minutes).minutes.do(self.retry_failed_calls)
        schedule.every(5).minutes.do(self.cleanup_expired_calls)
        schedule.every(10).minutes.do(self.cleanup_stale_resources)
        schedule.every().hour.do(self.load_config)  # Reload config every hour
        
        logger.info(f"Scheduler started with {interval_minutes} minute intervals")
        
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(30)  # Check every 30 seconds
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
        except Exception as e:
            logger.error(f"Error in scheduler: {str(e)}")
        finally:
            self.running = False
    
    def stop(self):
        """Stop the scheduler"""
        self.running = False
        logger.info("Scheduler stop requested")


# Global scheduler instance
retry_scheduler = RetryScheduler()


def run_scheduler():
    """Start the retry scheduler"""
    retry_scheduler.run_scheduler()


def stop_scheduler():
    """Stop the retry scheduler"""
    retry_scheduler.stop()


# Backward compatibility functions
def retry_failed_calls():
    """Legacy function for backward compatibility"""
    retry_scheduler.retry_failed_calls()
