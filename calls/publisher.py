import json
import logging
from kafka import KafkaProducer
from kafka.errors import KafkaError
from django.utils import timezone
from .models import DLQEntry
from config import Config

logger = logging.getLogger(__name__)

# Initialize Kafka producer with configuration
producer = KafkaProducer(
    bootstrap_servers=Config.KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda x: json.dumps(x, default=str).encode('utf-8'),
    retries=3,
    acks='all',
    enable_idempotence=True,
    max_in_flight_requests_per_connection=1
)


def publish_to_kafka(topic, payload, max_retries=3):
    """Generic function to publish messages to Kafka with DLQ support"""
    try:
        future = producer.send(topic, value=payload)
        record_metadata = future.get(timeout=10)
        logger.info(f"Message sent to {topic}: partition={record_metadata.partition}, offset={record_metadata.offset}")
        return True
        
    except KafkaError as e:
        logger.error(f"Failed to send message to {topic}: {str(e)}")
        send_to_dlq(topic, payload, str(e))
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending to {topic}: {str(e)}")
        send_to_dlq(topic, payload, str(e))
        return False


def send_to_dlq(original_topic, payload, error_message):
    """Send failed messages to Dead Letter Queue"""
    try:
        dlq_entry = DLQEntry.objects.create(
            topic=original_topic,
            payload=payload,
            error=error_message
        )
        logger.info(f"Message sent to DLQ: {dlq_entry.id}")
        
        # Also try to publish to DLQ Kafka topic
        dlq_payload = {
            'dlq_id': str(dlq_entry.id),
            'original_topic': original_topic,
            'original_payload': payload,
            'error': error_message,
            'timestamp': timezone.now().isoformat()
        }
        
        try:
            producer.send(Config.KAFKA_DLQ_TOPIC, value=dlq_payload)
        except Exception as dlq_error:
            logger.error(f"Failed to send to DLQ topic: {str(dlq_error)}")
            
    except Exception as e:
        logger.error(f"Failed to create DLQ entry: {str(e)}")


def publish_initiate_call_event(call_log):
    """Publish call initiation event to Kafka"""
    payload = {
        'call_id': call_log.call_id,
        'phone_number': call_log.phone_number,
        'campaign_id': call_log.campaign.id,
        'campaign_name': call_log.campaign.name,
        'status': call_log.status,
        'attempt_count': call_log.attempt_count,
        'max_attempts': call_log.max_attempts,
        'created_at': call_log.created_at.isoformat(),
        'last_attempt_at': call_log.last_attempt_at.isoformat() if call_log.last_attempt_at else None,
        'next_retry_at': call_log.next_retry_at.isoformat() if call_log.next_retry_at else None
    }
    
    success = publish_to_kafka(Config.KAFKA_INITIATE_CALL_TOPIC, payload)
    if success:
        logger.info(f"Call initiation event published: {call_log.call_id}")
    else:
        logger.error(f"Failed to publish call initiation event: {call_log.call_id}")
    
    return success


def publish_callback_event(call_log):
    """Publish callback event to Kafka"""
    payload = {
        'call_id': call_log.call_id,
        'phone_number': call_log.phone_number,
        'campaign_id': call_log.campaign.id,
        'status': call_log.status,
        'total_call_time': call_log.total_call_time,
        'external_call_id': call_log.external_call_id,
        'updated_at': call_log.updated_at.isoformat(),
        'error_message': call_log.error_message
    }
    
    success = publish_to_kafka(Config.KAFKA_CALLBACK_TOPIC, payload)
    if success:
        logger.info(f"Callback event published: {call_log.call_id} -> {call_log.status}")
    else:
        logger.error(f"Failed to publish callback event: {call_log.call_id}")
    
    return success


def publish_retry_event(call_log):
    """Publish retry event to Kafka"""
    payload = {
        'call_id': call_log.call_id,
        'phone_number': call_log.phone_number,
        'campaign_id': call_log.campaign.id,
        'status': call_log.status,
        'attempt_count': call_log.attempt_count,
        'max_attempts': call_log.max_attempts,
        'next_retry_at': call_log.next_retry_at.isoformat() if call_log.next_retry_at else None,
        'retry_reason': 'scheduled_retry'
    }
    
    success = publish_to_kafka(Config.KAFKA_INITIATE_CALL_TOPIC, payload)
    if success:
        logger.info(f"Retry event published: {call_log.call_id} (attempt {call_log.attempt_count})")
    else:
        logger.error(f"Failed to publish retry event: {call_log.call_id}")
    
    return success


def close_producer():
    """Close the Kafka producer"""
    try:
        producer.close()
        logger.info("Kafka producer closed")
    except Exception as e:
        logger.error(f"Error closing Kafka producer: {str(e)}")
