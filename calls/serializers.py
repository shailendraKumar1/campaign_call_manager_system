from rest_framework import serializers
from .models import CallLog, Campaign, PhoneNumber, CallMetrics, DLQEntry

class PhoneNumberSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneNumber
        fields = ['id', 'number', 'campaign', 'is_active', 'created_at']

class CallLogSerializer(serializers.ModelSerializer):
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)
    
    class Meta:
        model = CallLog
        fields = [
            'call_id', 'campaign', 'campaign_name', 'phone_number', 'status',
            'attempt_count', 'max_attempts', 'created_at', 'updated_at',
            'last_attempt_at', 'next_retry_at', 'total_call_time',
            'external_call_id', 'error_message'
        ]

class CampaignSerializer(serializers.ModelSerializer):
    phone_numbers = PhoneNumberSerializer(many=True, read_only=True)
    phone_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'description', 'is_active', 'created_at', 
            'updated_at', 'phone_numbers', 'phone_count'
        ]
    
    def get_phone_count(self, obj):
        return obj.phone_numbers.filter(is_active=True).count()

class CallMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CallMetrics
        fields = '__all__'

class DLQEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = DLQEntry
        fields = [
            'id', 'topic', 'error', 'retry_count', 'max_retries',
            'created_at', 'last_retry_at', 'processed', 'processed_at'
        ]
