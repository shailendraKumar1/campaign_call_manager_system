from django.urls import path
from .views import (
    InitiateCallView, BulkInitiateCallView, CallBackView, CampaignListCreateView, 
    CampaignDetailView, PhoneNumberListCreateView, metrics_view
)

urlpatterns = [
    # Call management
    path('api/v1/initiate-call/', InitiateCallView.as_view(), name='initiate-call'),
    path('api/v1/bulk-initiate-calls/', BulkInitiateCallView.as_view(), name='bulk-initiate-calls'),
    path('api/v1/callback/', CallBackView.as_view(), name='callback'),
    
    # Campaign management
    path('api/v1/campaigns/', CampaignListCreateView.as_view(), name='campaigns'),
    path('api/v1/campaigns/<int:campaign_id>/', CampaignDetailView.as_view(), name='campaign-detail'),
    path('api/v1/phone-numbers/', PhoneNumberListCreateView.as_view(), name='phone-numbers'),
    
    # Metrics and observability
    path('api/v1/metrics/', metrics_view, name='metrics'),
]
