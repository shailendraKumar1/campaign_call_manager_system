import json
import logging
import threading
import requests
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from django.utils import timezone
from django.db import transaction
from .models import CallLog, DLQEntry
from .publisher import send_to_dlq
from .utils import ConcurrencyManager, MetricsManager
from config import Config

logger = logging.getLogger(__name__)


class CallConsumer:
    """Enhanced Kafka consumer for call events with proper error handling"""
    
    def __init__(self):
        self.running = False
        self.consumer = None
    
    def start_initiated_call_consumer(self):
        """Consumer for call initiation events"""
        self.running = True
        
        try:
            self.consumer = KafkaConsumer(
                Config.KAFKA_INITIATE_CALL_TOPIC,
                bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=True,
                group_id='call_initiation_consumer_group'
            )
            
            logger.info(f"Started call initiation consumer for topic: {Config.KAFKA_INITIATE_CALL_TOPIC}")
            
            for message in self.consumer:
                if not self.running:
                    break
                
                try:
                    self.process_call_initiation(message.value)
                except Exception as e:
                    logger.error(f"Error processing call initiation message: {str(e)}")
                    send_to_dlq(Config.KAFKA_INITIATE_CALL_TOPIC, message.value, str(e))
                    
        except Exception as e:
            logger.error(f"Error in call initiation consumer: {str(e)}")
        finally:
            if self.consumer:
                self.consumer.close()
    
    def start_callback_consumer(self):
        """Consumer for callback events"""
        self.running = True
        
        try:
            self.consumer = KafkaConsumer(
                Config.KAFKA_CALLBACK_TOPIC,
                bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
                value_deserializer=lambda x: json.loads(x.decode('utf-8')),
                auto_offset_reset='latest',
                enable_auto_commit=True,
                group_id='callback_consumer_group'
            )
            
            logger.info(f"Started callback consumer for topic: {Config.KAFKA_CALLBACK_TOPIC}")
            
            for message in self.consumer:
                if not self.running:
                    break
                
                try:
                    self.process_callback_event(message.value)
                except Exception as e:
                    logger.error(f"Error processing callback message: {str(e)}")
                    send_to_dlq(Config.KAFKA_CALLBACK_TOPIC, message.value, str(e))
                    
        except Exception as e:
            logger.error(f"Error in callback consumer: {str(e)}")
        finally:
            if self.consumer:
                self.consumer.close()
    
    def process_call_initiation(self, data):
        """Process call initiation event"""
        call_id = data.get('call_id')
        phone_number = data.get('phone_number')
        campaign_id = data.get('campaign_id')
        
        if not all([call_id, phone_number, campaign_id]):
            raise ValueError("Missing required fields in call initiation event")
        
        logger.info(f"Processing call initiation: {call_id}")
        
        try:
            with transaction.atomic():
                # Update call log status
                call_log = CallLog.objects.select_for_update().get(call_id=call_id)
                call_log.status = 'PROCESSING'
                call_log.updated_at = timezone.now()
                call_log.save()
                
                # Make external call if mock service is enabled
                if Config.MOCK_SERVICE_ENABLED:
                    success = self.initiate_external_call(call_log)
                    if success:
                        call_log.status = 'INITIATED'
                    else:
                        call_log.status = 'FAILED'
                        call_log.error_message = 'Failed to initiate external call'
                    call_log.save()
                
                logger.info(f"Call initiation processed: {call_id} -> {call_log.status}")
                
        except CallLog.DoesNotExist:
            logger.error(f"Call log not found for call_id: {call_id}")
            raise
        except Exception as e:
            logger.error(f"Error processing call initiation {call_id}: {str(e)}")
            raise
    
    def process_callback_event(self, data):
        """Process callback event"""
        call_id = data.get('call_id')
        status = data.get('status')
        
        if not all([call_id, status]):
            raise ValueError("Missing required fields in callback event")
        
        logger.info(f"Processing callback: {call_id} -> {status}")
        
        try:
            with transaction.atomic():
                call_log = CallLog.objects.select_for_update().get(call_id=call_id)
                
                # Update retry count based on status
                if status in ['DISCONNECTED', 'RNR']:
                    # These statuses should increment retry count
                    if call_log.attempt_count < call_log.max_attempts:
                        # Will be handled by scheduler for retry
                        call_log.status = status
                    else:
                        # Max attempts reached
                        call_log.status = 'FAILED'
                        call_log.error_message = f'Max retry attempts reached ({call_log.max_attempts})'
                        # End concurrency tracking
                        ConcurrencyManager.end_call(call_id, call_log.phone_number)
                elif status == 'PICKED':
                    # Call was successful
                    call_log.status = 'COMPLETED'
                    # End concurrency tracking
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                else:
                    call_log.status = status
                
                call_log.updated_at = timezone.now()
                call_log.save()
                
                logger.info(f"Callback processed: {call_id} -> {call_log.status}")
                
        except CallLog.DoesNotExist:
            logger.error(f"Call log not found for call_id: {call_id}")
            raise
        except Exception as e:
            logger.error(f"Error processing callback {call_id}: {str(e)}")
            raise
    
    def initiate_external_call(self, call_log):
        """Make external API call to initiate the call"""
        try:
            payload = {
                'call_id': call_log.call_id,
                'phone_number': call_log.phone_number,
                'campaign_id': call_log.campaign.id,
                'campaign_name': call_log.campaign.name
            }
            
            response = requests.post(
                f"{Config.EXTERNAL_CALL_SERVICE_URL}/api/initiate-call",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                call_log.external_call_id = result.get('external_call_id')
                logger.info(f"External call initiated: {call_log.call_id} -> {call_log.external_call_id}")
                return True
            else:
                logger.error(f"External call failed: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making external call request: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error in external call: {str(e)}")
            return False
    
    def stop(self):
        """Stop the consumer"""
        self.running = False
        if self.consumer:
            self.consumer.close()
        logger.info("Consumer stopped")


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
            
            for entry in dlq_entries:
                try:
                    # Attempt to reprocess the message
                    success = DLQProcessor.reprocess_message(entry)
                    
                    if success:
                        entry.processed = True
                        entry.processed_at = timezone.now()
                    else:
                        entry.retry_count += 1
                        entry.last_retry_at = timezone.now()
                    
                    entry.save()
                    
                except Exception as e:
                    logger.error(f"Error reprocessing DLQ entry {entry.id}: {str(e)}")
                    entry.retry_count += 1
                    entry.last_retry_at = timezone.now()
                    entry.save()
            
            logger.info(f"Processed {len(dlq_entries)} DLQ entries")
            
        except Exception as e:
            logger.error(f"Error processing DLQ entries: {str(e)}")
    
    @staticmethod
    def reprocess_message(dlq_entry):
        """Attempt to reprocess a DLQ message"""
        try:
            consumer = CallConsumer()
            
            if dlq_entry.topic == Config.KAFKA_INITIATE_CALL_TOPIC:
                consumer.process_call_initiation(dlq_entry.payload)
            elif dlq_entry.topic == Config.KAFKA_CALLBACK_TOPIC:
                consumer.process_callback_event(dlq_entry.payload)
            else:
                logger.warning(f"Unknown topic in DLQ entry: {dlq_entry.topic}")
                return False
            
            return True
            
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
            
        except Exception as e:
            logger.error(f"Error cleaning up DLQ entries: {str(e)}")


# Global consumer instances - separate instance for each consumer type
initiate_call_consumer = CallConsumer()
callback_consumer = CallConsumer()


def start_initiated_call_consumer():
    """Start the call initiation consumer in a separate thread"""
    thread = threading.Thread(target=initiate_call_consumer.start_initiated_call_consumer)
    thread.daemon = True
    thread.start()
    return thread


def start_callback_consumer():
    """Start the callback consumer in a separate thread"""
    thread = threading.Thread(target=callback_consumer.start_callback_consumer)
    thread.daemon = True
    thread.start()
    return thread


def stop_consumers():
    """Stop all consumers"""
    initiate_call_consumer.stop()
    callback_consumer.stop()
