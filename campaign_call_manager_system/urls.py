"""
URL configuration for campaign_call_manager_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
import os

# Swagger/OpenAPI Schema Configuration
schema_view = get_schema_view(
    openapi.Info(
        title="Campaign Call Manager API",
        default_version='v1',
        description="""
        **Production-ready Django system for managing outbound call campaigns**
        
        Features:
        - Single & bulk call initiation (100+ concurrent calls)
        - Intelligent retry mechanism (DISCONNECTED/RNR auto-retry)
        - Real-time callback processing
        - Campaign & phone number management
        - System metrics & monitoring
        
        Authentication: Use `X-Auth-Token` header
        """,
        terms_of_service="https://www.example.com/terms/",
        contact=openapi.Contact(email="contact@example.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Swagger API Documentation
    re_path(r'^swagger(?P<format>\.json|\.yaml)$', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('api/docs/', schema_view.with_ui('swagger', cache_timeout=0), name='api-docs'),
]

# Use test URLs if in test mode, otherwise use regular URLs
if os.environ.get('DJANGO_SETTINGS_MODULE') == 'local_test_settings':
    urlpatterns.append(path('', include('test_urls')))
else:
    urlpatterns.append(path('', include('calls.urls')))
