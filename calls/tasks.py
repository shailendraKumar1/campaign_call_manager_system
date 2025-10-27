"""
Celery Tasks for Call Processing

Handles async call initiation, callback processing, and retry logic.
"""

import logging
import httpx
from datetime import timedelta
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from .models import CallLog, DLQEntry, Campaign, ConcurrencyControl
from .utils import ConcurrencyManager, MetricsManager, generate_call_id, CallQueueManager
from config import Config

logger = logging.getLogger(__name__)


def _save_to_dlq(topic, payload, error_message, retry_count=0):
    """Save failed task to Dead Letter Queue for manual review"""
    try:
        DLQEntry.objects.create(
            topic=topic,
            payload=payload,
            error_message=error_message,
            retry_count=retry_count
        )
    except Exception as e:
        logger.error(f"Failed to save to DLQ: {str(e)}")


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_external_callback(self, callback_data):
    """Process async callback from external service via Celery queue"""
    try:
        call_id = callback_data.get('call_id')
        status = callback_data.get('status')
        
        logger.info(f"[Callback Worker] Processing: {call_id} -> {status}")
        
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
                logger.info(f"[Callback Worker] ✅ Success: {call_id}")
                return {'success': True, 'call_id': call_id, 'status': status}
            
            elif response.status_code in [500, 503]:
                logger.warning(f"[Callback Worker] Retriable error {response.status_code}: {call_id}")
                raise self.retry(exc=Exception(f"HTTP {response.status_code}"))
            
            else:
                logger.error(f"[Callback Worker] ❌ Non-retriable {response.status_code}: {call_id}")
                return {'success': False, 'call_id': call_id, 'error': f"HTTP {response.status_code}"}
                
    except httpx.RequestError as e:
        logger.error(f"[Callback Worker] Request error: {call_id} - {str(e)}")
        if self.request.retries >= self.max_retries - 1:
            _save_to_dlq('external_callback', callback_data, 
                        f"Request error after {self.max_retries} retries: {str(e)}", 
                        self.request.retries)
        raise self.retry(exc=e)
        
    except Exception as e:
        logger.error(f"[Callback Worker] Unexpected error: {call_id} - {str(e)}", exc_info=True)
        _save_to_dlq('external_callback', callback_data, f"Unexpected error: {str(e)}", self.request.retries)
        return {'success': False, 'call_id': callback_data.get('call_id'), 'error': str(e)}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_call_initiation(self, call_id, phone_number, campaign_id):
    """Process call initiation - get CallLog, call external service, update status"""
    try:
        logger.info(f"Processing call: {call_id}")
        
        with transaction.atomic():
            call_log = CallLog.objects.select_for_update().get(call_id=call_id)
            
            # Check if queued call - start concurrency tracking if needed
            if not ConcurrencyControl.objects.filter(call_id=call_id).exists():
                can_initiate, _ = ConcurrencyManager.can_initiate_call(phone_number, campaign_id)
                if not can_initiate:
                    logger.info(f"Call queued - no capacity: {call_id}")
                    raise self.retry(countdown=30)
                
                if not ConcurrencyManager.start_call(call_id, phone_number, campaign_id):
                    logger.error(f"Failed to start tracking: {call_id}")
                    raise self.retry(countdown=30)
            
            call_log.status = 'PROCESSING'
            call_log.updated_at = timezone.now()
            call_log.save()
            
            # Initiate external call
            if Config.MOCK_SERVICE_ENABLED:
                success = initiate_external_call(call_log)
                call_log.status = 'INITIATED' if success else 'FAILED'
                
                if not success:
                    call_log.error_message = 'Failed to initiate external call'
                    ConcurrencyManager.end_call(call_id)
                    logger.error(f"External call failed: {call_id}")
                else:
                    logger.info(f"Call initiated: {call_id}")
                    
                call_log.save()
                
    except CallLog.DoesNotExist:
        logger.error(f"CallLog not found: {call_id}")
        return
        
    except Exception as e:
        logger.error(f"Error processing call: {str(e)}", exc_info=True)
        _save_to_dlq('call_initiation', 
                    {'call_id': call_id, 'phone_number': phone_number, 'campaign_id': campaign_id},
                    str(e), self.request.retries)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_callback_event(self, call_id, status, call_duration=None, external_call_id=None):
    """Process callback - update status, handle retry logic, manage concurrency"""
    try:
        logger.info(f"[Callback] {call_id} -> {status} ({call_duration}s)")
        
        with transaction.atomic():
            call_log = CallLog.objects.select_for_update().get(call_id=call_id)
            
            if call_duration:
                call_log.total_call_time = call_duration
            if external_call_id:
                call_log.external_call_id = external_call_id
            
            # Handle retry logic for failed calls
            if status in ['DISCONNECTED', 'RNR']:
                if call_log.attempt_count < call_log.max_attempts:
                    call_log.status = status
                    call_log.next_retry_at = timezone.now() + timedelta(minutes=5)
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                    logger.info(f"Retry scheduled: {call_id} ({call_log.attempt_count}/{call_log.max_attempts})")
                else:
                    call_log.status = 'FAILED'
                    call_log.error_message = f'Max retry attempts reached ({call_log.max_attempts})'
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                    logger.warning(f"Max retries reached: {call_id}")
                    
            elif status == 'PICKED':
                call_log.status = 'COMPLETED'
                ConcurrencyManager.end_call(call_id, call_log.phone_number)
                MetricsManager.increment_call_status_count('COMPLETED', call_duration or 0)
                logger.info(f"Call completed: {call_id}")
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
        _save_to_dlq('callback', {'call_id': call_id, 'status': status, 'call_duration': call_duration},
                    str(e), self.request.retries)
        raise self.retry(exc=e)


def initiate_external_call(call_log):
    """Make external API call using httpx"""
    try:
        payload = {
            'call_id': call_log.call_id,
            'phone_number': call_log.phone_number,
            'campaign_id': call_log.campaign.id,
            'campaign_name': call_log.campaign.name
        }
        
        logger.info(f"Calling external service: {call_log.call_id}")
        
        with httpx.Client(timeout=30.0, verify=False, http2=False) as client:
            response = client.post(
                f"{Config.EXTERNAL_CALL_SERVICE_URL}/api/initiate-call",
                json=payload
            )
        
        if response.status_code == 200:
            result = response.json()
            call_log.external_call_id = result.get('external_call_id')
            logger.info(f"External call initiated: {call_log.call_id}")
            return True
        
        logger.error(f"External call failed: {response.status_code}")
        return False
            
    except Exception as e:
        logger.error(f"External call error: {str(e)}")
        return False


@shared_task
def retry_failed_call(call_id):
    """Retry a failed call (triggered by scheduler)"""
    try:
        call_log = CallLog.objects.get(call_id=call_id)
        logger.info(f"Retrying call: {call_id} (attempt {call_log.attempt_count + 1})")
        process_call_initiation.delay(call_log.call_id, call_log.phone_number, call_log.campaign.id)
        
    except CallLog.DoesNotExist:
        logger.error(f"Call log not found for retry: {call_id}")
    except Exception as e:
        logger.error(f"Error retrying call {call_id}: {str(e)}")


@shared_task(bind=True)
def process_queue_batch(self, campaign_id):
    """Process queued calls as slots become available (auto-triggers if more remain)"""
    try:
        campaign = Campaign.objects.get(id=campaign_id, is_active=True)
        available_slots = ConcurrencyManager.get_available_slots()
        queue_size = CallQueueManager.get_queue_size(campaign_id)
        
        if available_slots == 0:
            return {'success': True, 'processed': 0, 'message': 'No available slots'}
        
        if queue_size == 0:
            return {'success': True, 'processed': 0, 'message': 'Queue empty'}
        
        logger.info(f"[Queue Processor] Campaign {campaign_id}: {available_slots} slots, {queue_size} queued")
        
        batch_size = min(available_slots, queue_size)
        queue_entries = CallQueueManager.pop_from_queue(campaign_id, batch_size)
        
        processed_count = 0
        failed_count = 0
        
        for entry in queue_entries:
            try:
                phone_number = entry['phone_number']
                
                # Skip duplicates
                if cache.get(f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"):
                    failed_count += 1
                    continue
                
                call_id = generate_call_id(campaign.id, phone_number)
                
                # Start tracking or put back in queue
                if not ConcurrencyManager.start_call(call_id, phone_number, campaign.id):
                    CallQueueManager.add_to_queue(campaign.id, [phone_number])
                    failed_count += 1
                    continue
                
                CallLog.objects.create(
                    call_id=call_id,
                    phone_number=phone_number,
                    campaign=campaign,
                    status='INITIATED',
                    attempt_count=1,
                    max_attempts=Config.MAX_RETRY_ATTEMPTS,
                    last_attempt_at=timezone.now()
                )
                
                MetricsManager.increment_call_status_count('INITIATED')
                process_call_initiation.delay(call_id, phone_number, campaign.id)
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"[Queue Processor] Error: {entry.get('phone_number')} - {str(e)}")
                failed_count += 1
        
        remaining_queue = CallQueueManager.get_queue_size(campaign_id)
        logger.info(f"[Queue Processor] Processed: {processed_count}, Failed: {failed_count}, Remaining: {remaining_queue}")
        
        # Auto-trigger next batch if more calls remain
        if remaining_queue > 0 and processed_count > 0:
            process_queue_batch.apply_async(args=[campaign_id], countdown=3)
        
        return {
            'success': True,
            'processed': processed_count,
            'failed': failed_count,
            'remaining_queue': remaining_queue
        }
        
    except Campaign.DoesNotExist:
        logger.error(f"[Queue Processor] Campaign {campaign_id} not found")
        return {'success': False, 'error': 'Campaign not found'}
    except Exception as e:
        logger.error(f"[Queue Processor] Error: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e)}
