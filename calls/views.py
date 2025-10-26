import logging
import time
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from django.db import transaction, OperationalError
from django.utils import timezone
from django.core.cache import cache
from .models import CallLog, Campaign, PhoneNumber, CallMetrics, ConcurrencyControl
from .serializers import CallLogSerializer, CampaignSerializer, PhoneNumberSerializer
from .tasks import process_call_initiation, process_callback_event
from .utils import ConcurrencyManager, MetricsManager, generate_call_id, CallValidationResult, is_valid_phone_number, CallQueueManager
from config import Config

logger = logging.getLogger(__name__)


class InitiateCallView(APIView):
    def post(self, request):
        """Initiate outbound call"""
        try:
            phone_number = request.data.get("phone_number")
            campaign_id = request.data.get("campaign_id")
            
            # Validate input
            if not phone_number or not campaign_id:
                return Response(
                    {"error": "phone_number and campaign_id are required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not is_valid_phone_number(phone_number):
                return Response(
                    {"error": "Invalid phone number format"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get campaign
            try:
                campaign = Campaign.objects.get(id=campaign_id, is_active=True)
            except Campaign.DoesNotExist:
                return Response(
                    {"error": "Campaign not found or inactive"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check concurrency and duplicate prevention
            can_initiate, validation_result = ConcurrencyManager.can_initiate_call(phone_number, campaign_id)
            if not can_initiate:
                # If it's a concurrency limit issue, queue the call instead of rejecting
                if validation_result == CallValidationResult.CAPACITY_LIMIT_REACHED:
                    call_id = generate_call_id(campaign_id, phone_number)
                    
                    with transaction.atomic():
                        # Create call log in INITIATED status (queued internally)
                        call_log = CallLog.objects.create(
                            call_id=call_id,
                            campaign=campaign,
                            phone_number=phone_number,
                            status="INITIATED",
                            attempt_count=1,
                            last_attempt_at=timezone.now()
                        )
                        
                        # Update metrics for initiated call
                        MetricsManager.increment_call_status_count('INITIATED')
                        
                        # Queue the call for later processing
                        task = process_call_initiation.delay(call_id, phone_number, campaign_id)
                        logger.info(f"Call queued due to capacity limit: {call_id}")
                        
                        # Return standard response format (same as immediate processing)
                        return Response(
                            CallLogSerializer(call_log).data, 
                            status=status.HTTP_201_CREATED
                        )
                else:
                    # For other validation failures (like duplicates), return appropriate error
                    if validation_result == CallValidationResult.DUPLICATE_CALL_IN_PROGRESS:
                        error_message = f"Call to {phone_number} already in progress"
                    else:
                        error_message = "Call initiation not allowed"
                    
                    return Response({"error": error_message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            call_id = generate_call_id(campaign_id, phone_number)
            
            with transaction.atomic():
                # Create call log
                call_log = CallLog.objects.create(
                    call_id=call_id,
                    campaign=campaign,
                    phone_number=phone_number,
                    status="INITIATED",
                    attempt_count=1,
                    last_attempt_at=timezone.now()
                )
                
                # Start concurrency tracking
                if not ConcurrencyManager.start_call(call_id, phone_number, campaign_id):
                    return Response(
                        {"error": "Failed to start call tracking"}, 
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                
                # Update metrics
                MetricsManager.increment_call_status_count('INITIATED')
                
                # Queue async task
                task = process_call_initiation.delay(call_id, phone_number, campaign_id)
                logger.info(f"Call initiated: {call_id}")
                
                return Response(
                    CallLogSerializer(call_log).data, 
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f"Error initiating call: {str(e)}", exc_info=True)
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class BulkInitiateCallView(APIView):
    """Bulk initiate calls for a campaign"""
    
    def post(self, request):
        """
        Bulk initiate calls
        
        Request body:
        {
            "campaign_id": 1,
            "phone_numbers": ["+1234567890", "+9876543210", ...],
            // OR
            "use_campaign_numbers": true  // Use all numbers from campaign
        }
        """
        try:
            campaign_id = request.data.get("campaign_id")
            phone_numbers = request.data.get("phone_numbers", [])
            use_campaign_numbers = request.data.get("use_campaign_numbers", False)
            
            # Validate campaign
            if not campaign_id:
                return Response(
                    {"error": "campaign_id is required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                campaign = Campaign.objects.get(id=campaign_id, is_active=True)
            except Campaign.DoesNotExist:
                return Response(
                    {"error": "Campaign not found or inactive"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get phone numbers
            if use_campaign_numbers:
                # Use all phone numbers from campaign
                campaign_phones = campaign.phone_numbers.all()
                phone_numbers = [pn.number for pn in campaign_phones]
            
            if not phone_numbers:
                return Response(
                    {"error": "No phone numbers provided. Use 'phone_numbers' array or 'use_campaign_numbers': true"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Remove duplicates
            phone_numbers = list(set(phone_numbers))
            
            # Validate each phone number format
            invalid_numbers = [pn for pn in phone_numbers if not is_valid_phone_number(pn)]
            if invalid_numbers:
                return Response(
                    {"error": f"Invalid phone numbers: {invalid_numbers[:5]}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get available concurrency slots
            available_slots = ConcurrencyManager.get_available_slots()
            
            # Split into immediate and queued
            immediate_count = min(available_slots, len(phone_numbers))
            immediate_numbers = phone_numbers[:immediate_count]
            queued_numbers = phone_numbers[immediate_count:]
            
            logger.info(
                f"[Bulk Call] Total: {len(phone_numbers)}, "
                f"Immediate: {immediate_count}, Queue: {len(queued_numbers)}, "
                f"Available slots: {available_slots}"
            )
            
            # Process immediate calls (within concurrency limit)
            call_ids = []
            failed_numbers = []
            
            for phone_number in immediate_numbers:
                try:
                    # Check for duplicate within window
                    duplicate_key = f"{Config.REDIS_DUPLICATE_PREVENTION_PREFIX}{phone_number}"
                    if cache.get(duplicate_key):
                        logger.warning(f"Duplicate call attempt for {phone_number} within window")
                        failed_numbers.append({
                            "phone_number": phone_number,
                            "reason": "Duplicate call within window"
                        })
                        continue
                    
                    # Start call tracking
                    call_id = generate_call_id(campaign_id, phone_number)
                    if not ConcurrencyManager.start_call(call_id, phone_number, campaign_id):
                        failed_numbers.append({
                            "phone_number": phone_number,
                            "reason": "Failed to start call tracking"
                        })
                        continue
                    
                    # Create call log
                    call_log = CallLog.objects.create(
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
                    
                    # Queue task
                    process_call_initiation.delay(call_id, phone_number, campaign_id)
                    
                    call_ids.append(call_id)
                    logger.info(f"Bulk call initiated: {call_id}")
                    
                except Exception as e:
                    logger.error(f"Error initiating call for {phone_number}: {str(e)}")
                    failed_numbers.append({
                        "phone_number": phone_number,
                        "reason": str(e)
                    })
            
            # Queue remaining calls
            queued_count = 0
            if queued_numbers:
                result = CallQueueManager.add_to_queue(campaign_id, queued_numbers)
                if result['success']:
                    queued_count = result['queued_count']
                    logger.info(f"[Bulk Call] Queued {queued_count} calls for campaign {campaign_id}")
                    
                    # Trigger queue processor
                    from .tasks import process_queue_batch
                    process_queue_batch.apply_async(
                        args=[campaign_id], 
                        countdown=2  # Start processing after 2 seconds
                    )
            
            # Prepare response
            batch_id = f"batch_{int(timezone.now().timestamp())}_{campaign_id}"
            response_data = {
                "success": True,
                "batch_id": batch_id,
                "campaign_id": campaign_id,
                "campaign_name": campaign.name,
                "total_requested": len(phone_numbers),
                "immediate_processed": len(call_ids),
                "queued_for_later": queued_count,
                "failed": len(failed_numbers),
                "call_ids": call_ids,
                "queue_info": {
                    "available_slots": available_slots,
                    "immediate_processed": len(call_ids),
                    "queued_pending": queued_count,
                    "total_in_queue": CallQueueManager.get_queue_size(campaign_id),
                    "message": f"✅ {len(call_ids)} calls started immediately. 📋 {queued_count} queued (will auto-process as slots become available)"
                }
            }
            
            if failed_numbers:
                response_data["failed_numbers"] = failed_numbers[:10]  # Limit to first 10
                response_data["failed_count"] = len(failed_numbers)
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error in bulk initiate calls: {str(e)}", exc_info=True)
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CallBackView(APIView):
    def put(self, request):
        """Handle callback events from external call service"""
        call_id = request.data.get("call_id")
        status_val = request.data.get("status")
        call_duration = request.data.get("call_duration")
        external_call_id = request.data.get("external_call_id")
        
        if not call_id or not status_val:
            return Response(
                {"error": "call_id and status are required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        valid_statuses = ['PICKED', 'DISCONNECTED', 'RNR', 'FAILED']
        if status_val not in valid_statuses:
            return Response(
                {"error": f"Invalid status. Must be one of: {valid_statuses}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Try to update database with retry logic
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    try:
                        call_log = CallLog.objects.select_for_update().get(call_id=call_id)
                    except CallLog.DoesNotExist:
                        return Response(
                            {"error": "Call not found"}, 
                            status=status.HTTP_404_NOT_FOUND
                        )
                    
                    # Update call log
                    call_log.status = status_val
                    call_log.updated_at = timezone.now()
                    
                    if call_duration:
                        call_log.total_call_time = call_duration
                    
                    if external_call_id:
                        call_log.external_call_id = external_call_id
                    
                    call_log.save()
                    
                    # Update metrics
                    MetricsManager.increment_call_status_count(status_val, call_duration)
                    
                    # Process callback async (additional processing)
                    process_callback_event.delay(call_id, status_val, call_duration, external_call_id)
                    logger.info(f"Callback: {call_id} -> {status_val}")
                    
                    return Response({
                        "success": True,
                        "call_id": call_id,
                        "status": status_val
                    })
                    
            except OperationalError as db_error:
                # Database connection/operational error - retry
                if attempt < max_retries - 1:
                    logger.warning(f"DB error on callback (attempt {attempt + 1}/{max_retries}): {str(db_error)}")
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    # Max retries reached - save to DLQ for manual processing
                    logger.error(f"DB error after {max_retries} attempts: {str(db_error)}")
                    try:
                        from calls.models import DLQEntry
                        DLQEntry.objects.create(
                            topic='callback_db_failure',
                            payload={
                                'call_id': call_id,
                                'status': status_val,
                                'call_duration': call_duration,
                                'external_call_id': external_call_id
                            },
                            error_message=f"Database error after {max_retries} retries: {str(db_error)}",
                            retry_count=max_retries
                        )
                    except Exception as dlq_error:
                        logger.critical(f"Failed to save callback to DLQ: {str(dlq_error)}")
                    
                    return Response(
                        {"error": "Database temporarily unavailable", "retry_after": 60}, 
                        status=status.HTTP_503_SERVICE_UNAVAILABLE
                    )
            
            except Exception as e:
                # Other errors - don't retry
                logger.error(f"Error processing callback: {str(e)}", exc_info=True)
                return Response(
                    {"error": "Internal server error"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


class CampaignListCreateView(APIView):
    def get(self, request):
        """List all active campaigns"""
        campaigns = Campaign.objects.filter(is_active=True).prefetch_related('phone_numbers')
        serializer = CampaignSerializer(campaigns, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """Create a new campaign"""
        try:
            serializer = CampaignSerializer(data=request.data)
            if serializer.is_valid():
                campaign = serializer.save()
                logger.info(f"Campaign created: {campaign.name}")
                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error creating campaign: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CampaignDetailView(APIView):
    def get(self, request, campaign_id):
        """Get campaign details"""
        try:
            campaign = Campaign.objects.prefetch_related('phone_numbers').get(
                id=campaign_id, is_active=True
            )
            serializer = CampaignSerializer(campaign)
            return Response(serializer.data)
        except Campaign.DoesNotExist:
            return Response(
                {"error": "Campaign not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )


class PhoneNumberListCreateView(APIView):
    def post(self, request):
        """Add phone numbers to a campaign"""
        try:
            campaign_id = request.data.get('campaign_id')
            phone_numbers = request.data.get('phone_numbers', [])
            
            if not campaign_id or not phone_numbers:
                return Response(
                    {"error": "campaign_id and phone_numbers are required"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                campaign = Campaign.objects.get(id=campaign_id, is_active=True)
            except Campaign.DoesNotExist:
                return Response(
                    {"error": "Campaign not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            created_numbers = []
            errors = []
            
            for number in phone_numbers:
                if not is_valid_phone_number(number):
                    errors.append(f"Invalid phone number: {number}")
                    continue
                
                phone_number, created = PhoneNumber.objects.get_or_create(
                    campaign=campaign,
                    number=number,
                    defaults={'is_active': True}
                )
                
                if created:
                    created_numbers.append(number)
            
            response_data = {
                "created_count": len(created_numbers),
                "created_numbers": created_numbers,
                "errors": errors
            }
            
            logger.info(f"Added {len(created_numbers)} numbers to campaign {campaign_id}")
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error adding phone numbers: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
def metrics_view(request):
    """Get call metrics and observability data"""
    try:
        # Current concurrent calls
        current_concurrent = ConcurrencyManager.get_current_concurrent_count()
        
        # Recent metrics (last 7 days)
        from datetime import date, timedelta
        end_date = date.today()
        start_date = end_date - timedelta(days=7)
        
        recent_metrics = CallMetrics.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).order_by('-date')
        
        metrics_data = []
        for metric in recent_metrics:
            metrics_data.append({
                'date': metric.date,
                'total_calls_initiated': metric.total_calls_initiated,
                'total_calls_picked': metric.total_calls_picked,
                'total_calls_disconnected': metric.total_calls_disconnected,
                'total_calls_rnr': metric.total_calls_rnr,
                'total_calls_failed': metric.total_calls_failed,
                'total_retries': metric.total_retries,
                'peak_concurrent_calls': metric.peak_concurrent_calls,
                'total_call_duration_seconds': metric.total_call_duration_seconds,
                'dlq_entries_created': metric.dlq_entries_created,
            })
        
        response_data = {
            'current_concurrent_calls': current_concurrent,
            'max_concurrent_calls': Config.MAX_CONCURRENT_CALLS,
            'recent_metrics': metrics_data,
            'system_status': 'healthy' if current_concurrent < Config.MAX_CONCURRENT_CALLS else 'at_capacity'
        }
        
        return Response(response_data)
        
    except Exception as e:
        logger.error(f"Error getting metrics: {str(e)}")
        return Response(
            {"error": "Internal server error"}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
