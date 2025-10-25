import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view
from django.db import transaction
from django.utils import timezone
from .models import CallLog, Campaign, PhoneNumber, CallMetrics, ConcurrencyControl
from .serializers import CallLogSerializer, CampaignSerializer, PhoneNumberSerializer
from .publisher import publish_initiate_call_event, publish_callback_event
from .utils import (
    ConcurrencyManager, MetricsManager, generate_call_id, 
    is_valid_phone_number
)
from config import Config

logger = logging.getLogger(__name__)


class InitiateCallView(APIView):
    def post(self, request):
        """Initiate a new outbound call with concurrency and duplicate prevention"""
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
            can_initiate, reason = ConcurrencyManager.can_initiate_call(phone_number, campaign_id)
            if not can_initiate:
                return Response(
                    {"error": reason}, 
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )
            
            # Generate unique call ID
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
                
                # Publish to Kafka
                publish_initiate_call_event(call_log)
                
                logger.info(f"Call initiated: {call_id} for {phone_number}")
                
                return Response(
                    CallLogSerializer(call_log).data, 
                    status=status.HTTP_201_CREATED
                )
                
        except Exception as e:
            logger.error(f"Error initiating call: {str(e)}")
            return Response(
                {"error": "Internal server error"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CallBackView(APIView):
    def put(self, request):
        """Handle callback events from external call service"""
        try:
            call_id = request.data.get("call_id")
            status_val = request.data.get("status")
            call_duration = request.data.get("call_duration")  # in seconds
            external_call_id = request.data.get("external_call_id")
            
            # Validate input
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
                
                # End concurrency tracking for final statuses
                if status_val in ['PICKED', 'FAILED']:
                    ConcurrencyManager.end_call(call_id, call_log.phone_number)
                
                # Update metrics
                MetricsManager.increment_call_status_count(status_val, call_duration)
                
                # Publish callback event
                publish_callback_event(call_log)
                
                logger.info(f"Callback processed: {call_id} -> {status_val}")
                
                return Response({
                    "success": True,
                    "call_id": call_id,
                    "status": status_val
                })
                
        except Exception as e:
            logger.error(f"Error processing callback: {str(e)}")
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
