"""
Celery Tasks for Call Processing

This module replaces Kafka consumers with Celery tasks.
Tasks are executed asynchronously by Celery workers.
"""

import logging
import asyncio
import httpx
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import CallLog, DLQEntry
from .utils import ConcurrencyManager, MetricsManager, CallValidationResult
from config import Config

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_external_callback(self, callback_data):
    """
    Process callback from external service (mock_service) via Celery queue
    
    This task is queued by the external service instead of calling the API directly.
    Benefits:
    - Decouples external service from main API
    - Adds retry logic and error handling
    - Better scalability (callbacks processed by workers)
    - Prevents callback API overload
    
    Args:
        callback_data: Dictionary with callback information
            {
                'call_id': str,
                'status': str (PICKED/DISCONNECTED/RNR),
                'call_duration': int,
                'external_call_id': str
            }
    """
    try:
        call_id = callback_data.get('call_id')
        status = callback_data.get('status')
        call_duration = callback_data.get('call_duration')
        external_call_id = callback_data.get('external_call_id')
        
        logger.info(f"[Callback Worker] Processing external callback: {call_id} -> {status}")
        
        # Call internal callback API
        with httpx.Client(timeout=10.0, verify=False, http2=False) as client:
            response = client.put(
                f"http://localhost:8000/api/v1/callback/",
                json=callback_data,
                headers={
                    'X-Auth-Token': Config.X_AUTH_TOKEN,
                    'Content-Type': 'application/json'
                }
            )
            
            if response.status_code == 200:
                logger.info(f"[Callback Worker] ✅ Callback processed successfully: {call_id}")
                return {
                    'success': True,
                    'call_id': call_id,
                    'status': status
                }
            elif response.status_code in [500, 503]:
                # Retriable errors - retry the task
                logger.warning(f"[Callback Worker] Retriable error ({response.status_code}): {call_id}")
                raise self.retry(exc=Exception(f"HTTP {response.status_code}"))
            else:
                # Non-retriable errors (404, 400, etc)
                logger.error(f"[Callback Worker] ❌ Non-retriable error ({response.status_code}): {call_id}")
                return {
                    'success': False,
                    'call_id': call_id,
                    'error': f"HTTP {response.status_code}"
                }
                
    except httpx.RequestError as e:
        # Network/connection errors - retry
        logger.error(f"[Callback Worker] Request error for {call_id}: {str(e)}")
        try:
            # Save to DLQ before final retry
            if self.request.retries >= self.max_retries - 1:
                DLQEntry.objects.create(
                    topic='external_callback',
                    payload=callback_data,
                    error_message=f"Request error after {self.max_retries} retries: {str(e)}",
                    retry_count=self.request.retries
                )
        except Exception as dlq_error:
            logger.error(f"Failed to save to DLQ: {str(dlq_error)}")
        
        raise self.retry(exc=e)
        
    except Exception as e:
        # Unexpected errors
        logger.error(f"[Callback Worker] Unexpected error for {call_id}: {str(e)}", exc_info=True)
        
        # Save to DLQ
        try:
            DLQEntry.objects.create(
                topic='external_callback',
                payload=callback_data,
                error_message=f"Unexpected error: {str(e)}",
                retry_count=self.request.retries
            )
        except Exception as dlq_error:
            logger.error(f"Failed to save to DLQ: {str(dlq_error)}")
        
        return {
            'success': False,
            'call_id': callback_data.get('call_id'),
            'error': str(e)
        }


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_call_initiation(self, call_id, phone_number, campaign_id):
    """
    Process call initiation event (replaces Kafka consumer)
    
    This task:
    1. Gets CallLog from database
    2. Calls external service to initiate call
    3. Updates CallLog with external_call_id
    
    Args:
        call_id: Unique call identifier
        phone_number: Phone number to call
        campaign_id: Campaign ID
    """
    try:
        logger.info(f"Processing call: {call_id}")
        
        with transaction.atomic():
            # Get call log
            call_log = CallLog.objects.select_for_update().get(call_id=call_id)
            
            # Check if this call needs concurrency tracking (for queued calls)
            # If concurrency tracking doesn't exist, this was a queued call
            from .models import ConcurrencyControl
            has_concurrency_tracking = ConcurrencyControl.objects.filter(call_id=call_id).exists()
            
            if not has_concurrency_tracking:
                # This was a queued call, check if capacity is available now
                can_initiate, validation_result = ConcurrencyManager.can_initiate_call(phone_number, campaign_id)
                if not can_initiate:
                    # Still no capacity, retry later
                    logger.info(f"Call still queued due to capacity: {call_id}")
                    raise self.retry(countdown=30)  # Retry in 30 seconds
                
                # Capacity available, start concurrency tracking
                if not ConcurrencyManager.start_call(call_id, phone_number, campaign_id):
                    logger.error(f"Failed to start call tracking for queued call: {call_id}")
                    raise self.retry(countdown=30)
            
            call_log.status = 'PROCESSING'
            call_log.updated_at = timezone.now()
            call_log.save()
            
            # Make external call
            if Config.MOCK_SERVICE_ENABLED:
                success = initiate_external_call(call_log)
                
                if success:
                    call_log.status = 'INITIATED'
                    logger.info(f"Call initiated: {call_id}")
                else:
                    call_log.status = 'FAILED'
                    call_log.error_message = 'Failed to initiate external call'
                    logger.error(f"External call failed: {call_id}")
                    # End concurrency tracking for failed calls
                    ConcurrencyManager.end_call(call_id)
                call_log.save()
                
    except CallLog.DoesNotExist:
        logger.error(f"CallLog not found: {call_id}")
        # Don't retry if record doesn't exist
        return
        
    except Exception as e:
        logger.error(f"Error processing call: {str(e)}", exc_info=True)
        
        # Save to DLQ for manual review
        try:
            DLQEntry.objects.create(
                topic='call_initiation',
                payload={'call_id': call_id, 'phone_number': phone_number, 'campaign_id': campaign_id},
                error_message=str(e),
                retry_count=self.request.retries
            )
            logger.info(f"Saved to DLQ: {call_id}")
        except Exception as dlq_error:
            logger.error(f"Failed to save to DLQ: {str(dlq_error)}")
        
        # Retry task
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_callback_event(self, call_id, status, call_duration=None, external_call_id=None):
    """
    Process callback event (replaces Kafka consumer)
    
    This task:
    1. Gets CallLog from database
    2. Updates status based on callback
    3. Handles retry logic for DISCONNECTED/RNR
    4. Ends concurrency tracking for final statuses
    
    Args:
        call_id: Unique call identifier
        status: Call status (PICKED, DISCONNECTED, RNR, FAILED)
        call_duration: Duration of call in seconds
        external_call_id: External service call ID
    """
    try:
        logger.info(
            f"[External API] [STEP 8-9] Callback Received | "
            f"call_id={call_id}, status={status}, duration={call_duration}s"
        )
        
        with transaction.atomic():
            call_log = CallLog.objects.select_for_update().get(call_id=call_id)
            
            # Update call duration if provided
            if call_duration:
                call_log.total_call_time = call_duration
            
            # Update external call ID if provided
            if external_call_id:
                call_log.external_call_id = external_call_id
            
            # Handle status-specific logic
            if status in ['DISCONNECTED', 'RNR']:
                if call_log.attempt_count < call_log.max_attempts:
                    # Schedule retry
                    call_log.status = status
                    from datetime import timedelta
                    call_log.next_retry_at = timezone.now() + timedelta(minutes=5)
                    # End concurrency tracking so retry can start
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                    logger.info(f"Retry scheduled: {call_id} (attempt {call_log.attempt_count}/{call_log.max_attempts})")
                else:
                    # Max attempts reached
                    call_log.status = 'FAILED'
                    call_log.error_message = f'Max retry attempts reached ({call_log.max_attempts})'
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                    logger.warning(f"Max retries reached: {call_id}")
                    
            elif status == 'PICKED':
                # Call successful
                call_log.status = 'COMPLETED'
                ConcurrencyManager.end_call(call_id, call_log.phone_number)
                MetricsManager.increment_call_status_count('COMPLETED', call_duration or 0)
                logger.info(f"Call completed: {call_id}")
                
                # Auto-trigger queue processor (slot now available)
                process_queue_batch.delay(call_log.campaign.id)
                
            else:
                call_log.status = status
            
            call_log.updated_at = timezone.now()
            call_log.save()
            
    except CallLog.DoesNotExist:
        logger.error(f"CallLog not found: {call_id}")
        return
        
    except Exception as e:
        logger.error(f"Error processing callback: {str(e)}", exc_info=True)
        
        # Save to DLQ
        try:
            DLQEntry.objects.create(
                topic='callback',
                payload={'call_id': call_id, 'status': status, 'call_duration': call_duration},
                error_message=str(e),
                retry_count=self.request.retries
            )
        except Exception as dlq_error:
            logger.error(f"Failed to save to DLQ: {str(dlq_error)}")
        
        # Retry task
        raise self.retry(exc=e)


def initiate_external_call(call_log):
    """
    Make external API call using httpx (modern HTTP client)
    
    Args:
        call_log: CallLog instance
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        payload = {
            'call_id': call_log.call_id,
            'phone_number': call_log.phone_number,
            'campaign_id': call_log.campaign.id,
            'campaign_name': call_log.campaign.name
        }
        
        logger.info(f"Calling external service: {call_log.call_id}")
        
        # Using httpx sync client (better performance than requests)
        # Set verify=False for local development, http2=False for compatibility
        with httpx.Client(timeout=30.0, verify=False, http2=False) as client:
            response = client.post(
                f"{Config.EXTERNAL_CALL_SERVICE_URL}/api/initiate-call",
                json=payload
            )
        
        if response.status_code == 200:
            result = response.json()
            call_log.external_call_id = result.get('external_call_id')
            logger.info(f"External call initiated: {call_log.call_id} -> {call_log.external_call_id}")
            return True
        else:
            logger.error(f"External call failed: {response.status_code}")
            return False
            
    except httpx.RequestError as e:
        logger.error(f"External call request error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in external call: {str(e)}")
        return False


@shared_task
def retry_failed_call(call_id):
    """
    Retry a failed call (called by scheduler)
    
    This task is triggered by the retry scheduler for calls with
    status DISCONNECTED or RNR that are eligible for retry.
    
    Args:
        call_id: Call ID to retry
    """
    try:
        call_log = CallLog.objects.get(call_id=call_id)
        
        logger.info(f"[Celery Task] Retrying call: {call_id} (attempt {call_log.attempt_count + 1})")
        
        # Trigger call initiation task
        process_call_initiation.delay(
            call_log.call_id,
            call_log.phone_number,
            call_log.campaign.id
        )
        
    except CallLog.DoesNotExist:
        logger.error(f"[Celery Task] Call log not found for retry: {call_id}")
    except Exception as e:
        logger.error(f"[Celery Task] Error retrying call {call_id}: {str(e)}")


@shared_task(bind=True)
def process_queue_batch(self, campaign_id):
    """
    Process queued calls batch by batch as slots become available
    
    This task:
    1. Checks available concurrency slots
    2. Pops calls from Redis queue (FIFO)
    3. Initiates calls up to available slots
    4. Auto-triggers itself if more calls remain in queue
    
    Triggered by:
    - BulkInitiateCallView when calls are queued
    - After callbacks when calls complete
    - Periodically by Celery Beat (every minute)
    
    Args:
        campaign_id: Campaign ID
    """
    from .models import CallLog, Campaign
    from .utils import ConcurrencyManager, MetricsManager, generate_call_id, CallQueueManager
    from django.core.cache import cache
    from config import Config
    
    try:
        # Get campaign
        try:
            campaign = Campaign.objects.get(id=campaign_id, is_active=True)
        except Campaign.DoesNotExist:
            logger.error(f"[Queue Processor] Campaign {campaign_id} not found")
            return {'success': False, 'error': 'Campaign not found'}
        
        # Check available slots
        available_slots = ConcurrencyManager.get_available_slots()
        
        if available_slots == 0:
            logger.info(f"[Queue Processor] No available slots for campaign {campaign_id}")
            return {
                'success': True,
                'processed': 0,
                'available_slots': 0,
                'message': 'No available slots'
            }
        
        # Check queue size
        queue_size = CallQueueManager.get_queue_size(campaign_id)
        if queue_size == 0:
            logger.info(f"[Queue Processor] Queue empty for campaign {campaign_id}")
            return {
                'success': True,
                'processed': 0,
                'queue_size': 0,
                'message': 'Queue empty'
            }
        
        logger.info(
            f"[Queue Processor] Campaign {campaign_id}: "
            f"Available slots: {available_slots}, Queue size: {queue_size}"
        )
        
        # Pop calls from queue
        batch_size = min(available_slots, queue_size)
        queue_entries = CallQueueManager.pop_from_queue(campaign_id, batch_size)
        
        processed_count = 0
        failed_count = 0
        
        # Process each queued call
        for entry in queue_entries:
            try:
                phone_number = entry['phone_number']
                
                # Check for duplicate
                duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                if cache.get(duplicate_key):
                    logger.warning(f"[Queue Processor] Duplicate: {phone_number}")
                    failed_count += 1
                    continue
                
                # Generate call ID
                call_id = generate_call_id(campaign.id, phone_number)
                
                # Start call tracking
                if not ConcurrencyManager.start_call(call_id, phone_number, campaign.id):
                    logger.error(f"[Queue Processor] Failed to track: {phone_number}")
                    # Put back in queue
                    CallQueueManager.add_to_queue(campaign.id, [phone_number])
                    failed_count += 1
                    continue
                
                # Create call log
                CallLog.objects.create(
                    call_id=call_id,
                    phone_number=phone_number,
                    campaign=campaign,
                    status='INITIATED',
                    attempt_count=1,
                    max_attempts=Config.MAX_RETRY_ATTEMPTS,
                    last_attempt_at=timezone.now()
                )
                
                # Update metrics
                MetricsManager.increment_call_status_count('INITIATED')
                
                # Queue call initiation task
                process_call_initiation.delay(call_id, phone_number, campaign.id)
                
                processed_count += 1
                logger.info(f"[Queue Processor] ✅ Processed from queue: {call_id}")
                
            except Exception as e:
                logger.error(f"[Queue Processor] Error processing {entry.get('phone_number')}: {str(e)}")
                failed_count += 1
        
        # Check if more calls remain in queue
        remaining_queue = CallQueueManager.get_queue_size(campaign_id)
        
        logger.info(
            f"[Queue Processor] Campaign {campaign_id}: "
            f"Processed: {processed_count}, Failed: {failed_count}, "
            f"Remaining in queue: {remaining_queue}"
        )
        
        # Auto-trigger next batch if queue has more calls and we successfully processed some
        if remaining_queue > 0 and processed_count > 0:
            logger.info(f"[Queue Processor] 🔄 Triggering next batch for campaign {campaign_id}")
            process_queue_batch.apply_async(
                args=[campaign_id],
                countdown=3  # Process next batch after 3 seconds
            )
        
        return {
            'success': True,
            'campaign_id': campaign_id,
            'processed': processed_count,
            'failed': failed_count,
            'remaining_queue': remaining_queue,
            'available_slots': available_slots,
            'message': f'Processed {processed_count} calls from queue'
        }
        
    except Exception as e:
        logger.error(f"[Queue Processor] Unexpected error for campaign {campaign_id}: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }
