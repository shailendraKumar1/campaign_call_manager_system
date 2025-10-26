from django.db import models
from django.utils import timezone
import uuid


class Campaign(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name


class PhoneNumber(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='phone_numbers')
    number = models.CharField(max_length=15, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['campaign', 'number']
    
    def __str__(self):
        return f"{self.campaign.name} - {self.number}"


class CallLog(models.Model):
    CALL_STATUS_CHOICES = [
        ('INITIATED', 'Initiated'),
        ('QUEUED', 'Queued'),
        ('PROCESSING', 'Processing'),
        ('PICKED', 'Picked'),
        ('DISCONNECTED', 'Disconnected'),
        ('RNR', 'Ring No Response'),
        ('FAILED', 'Failed'),
        ('RETRYING', 'Retrying'),
        ('COMPLETED', 'Completed'),
    ]
    
    call_id = models.CharField(max_length=100, unique=True, db_index=True)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='call_logs')
    phone_number = models.CharField(max_length=15, db_index=True)
    status = models.CharField(max_length=30, choices=CALL_STATUS_CHOICES, default='INITIATED')
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    total_call_time = models.IntegerField(null=True, blank=True)  # seconds
    external_call_id = models.CharField(max_length=100, null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['campaign', 'phone_number']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.call_id} - {self.status}"


class RetryRule(models.Model):
    DAY_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]
    
    name = models.CharField(max_length=100)
    day_of_week = models.CharField(max_length=9, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    max_attempts = models.IntegerField(default=3)
    retry_interval_minutes = models.IntegerField(default=60)  # minutes between retries
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, null=True, blank=True)  # nullable means global rule
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['campaign', 'day_of_week', 'start_time', 'end_time']
    
    def __str__(self):
        scope = f"Campaign: {self.campaign.name}" if self.campaign else "Global"
        return f"{self.name} - {self.day_of_week} {self.start_time}-{self.end_time} ({scope})"


class DLQEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField()
    error = models.TextField()
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    last_retry_at = models.DateTimeField(null=True, blank=True)
    processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['processed', 'retry_count']),
        ]
    
    def __str__(self):
        return f"DLQ Entry {self.id} - {self.topic}"


class CallMetrics(models.Model):
    """Daily aggregated metrics for observability"""
    date = models.DateField(unique=True)
    total_calls_initiated = models.IntegerField(default=0)
    total_calls_picked = models.IntegerField(default=0)
    total_calls_disconnected = models.IntegerField(default=0)
    total_calls_rnr = models.IntegerField(default=0)
    total_calls_failed = models.IntegerField(default=0)
    total_retries = models.IntegerField(default=0)
    peak_concurrent_calls = models.IntegerField(default=0)
    total_call_duration_seconds = models.BigIntegerField(default=0)
    dlq_entries_created = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
    
    def __str__(self):
        return f"Metrics for {self.date}"


class ConcurrencyControl(models.Model):
    """Track active calls for concurrency control"""
    call_id = models.CharField(max_length=100, unique=True)
    phone_number = models.CharField(max_length=15, db_index=True)
    campaign_id = models.IntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['started_at']),
        ]
    
    def __str__(self):
        return f"Active call: {self.call_id}"
