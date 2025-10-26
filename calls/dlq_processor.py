"""
Dead Letter Queue (DLQ) Processor

Handles processing of failed tasks from DLQ entries.
Works with Celery tasks instead of Kafka consumers.
"""

import logging
from django.utils import timezone
from .models import DLQEntry
from .tasks import process_call_initiation, process_callback_event
from config import Config

logger = logging.getLogger(__name__)


class DLQProcessor:
    """Process Dead Letter Queue entries"""
    
    @staticmethod
    def process_dlq_entries():
        """Process unprocessed DLQ entries"""
        try:
            # Get unprocessed entries that haven't exceeded max retries
            dlq_entries = DLQEntry.objects.filter(
                processed=False,
                retry_count__lt=3
            ).order_by('created_at')[:100]  # Process in batches
            
            processed_count = 0
            for entry in dlq_entries:
                try:
                    # Attempt to reprocess the message using Celery tasks
                    success = DLQProcessor.reprocess_message(entry)
                    
                    if success:
                        entry.processed = True
                        entry.processed_at = timezone.now()
                        processed_count += 1
                    else:
                        entry.retry_count += 1
                        entry.last_retry_at = timezone.now()
                    
                    entry.save()
                    
                except Exception as e:
                    logger.error(f"Error reprocessing DLQ entry {entry.id}: {str(e)}")
                    entry.retry_count += 1
                    entry.last_retry_at = timezone.now()
                    entry.save()
            
            logger.info(f"Processed {processed_count} DLQ entries successfully")
            
        except Exception as e:
            logger.error(f"Error processing DLQ entries: {str(e)}")
    
    @staticmethod
    def reprocess_message(dlq_entry):
        """
        Attempt to reprocess a DLQ message by triggering Celery tasks
        
        Args:
            dlq_entry: DLQEntry instance
            
        Returns:
            bool: True if successfully queued, False otherwise
        """
        try:
            payload = dlq_entry.payload
            
            # Determine which task to trigger based on topic
            if dlq_entry.topic == 'call_initiation':
                # Trigger call initiation task
                process_call_initiation.delay(
                    payload.get('call_id'),
                    payload.get('phone_number'),
                    payload.get('campaign_id')
                )
                logger.info(f"Re-queued call initiation for DLQ entry {dlq_entry.id}")
                return True
                
            elif dlq_entry.topic == 'callback':
                # Trigger callback processing task
                process_callback_event.delay(
                    payload.get('call_id'),
                    payload.get('status'),
                    payload.get('call_duration'),
                    payload.get('external_call_id')
                )
                logger.info(f"Re-queued callback processing for DLQ entry {dlq_entry.id}")
                return True
                
            else:
                logger.warning(f"Unknown topic in DLQ entry: {dlq_entry.topic}")
                return False
            
        except Exception as e:
            logger.error(f"Error reprocessing message: {str(e)}")
            return False
    
    @staticmethod
    def cleanup_old_dlq_entries():
        """Clean up old processed DLQ entries"""
        try:
            cutoff_date = timezone.now() - timezone.timedelta(days=Config.DLQ_RETENTION_DAYS)
            
            deleted_count = DLQEntry.objects.filter(
                processed=True,
                processed_at__lt=cutoff_date
            ).delete()[0]
            
            logger.info(f"Cleaned up {deleted_count} old DLQ entries")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up DLQ entries: {str(e)}")
            return 0
