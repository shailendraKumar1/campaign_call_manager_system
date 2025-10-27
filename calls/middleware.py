"""
Custom middleware for the Campaign Call Manager System
"""
import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from rest_framework import status
from config import Config
import os

logger = logging.getLogger(__name__)


class AuthTokenMiddleware(MiddlewareMixin):
    """
    Middleware to authenticate requests using X-Auth-Token header
    
    Validates that incoming requests contain a valid authentication token
    in the X-Auth-Token header.
    
    Excluded paths (no authentication required):
    - /admin/
    - /health/
    - /docs/
    - /swagger/
    - /redoc/
    - /api/docs/
    """
    
    # Paths that don't require authentication
    EXCLUDED_PATHS = [
        '/admin/',
        '/health/',
        '/docs/',
        '/static/',
        '/swagger',      # Swagger UI
        '/redoc',        # ReDoc UI
        '/api/docs/',    # API Documentation
    ]
    
    # HTTP methods that don't require authentication for some endpoints
    SAFE_METHODS = ['OPTIONS', 'HEAD']
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Get the expected token from environment or use default for development
        self.expected_token = os.getenv('X_AUTH_TOKEN', 'dev-token-12345')
        self.auth_enabled = os.getenv('AUTH_ENABLED', 'true').lower() == 'true'
        super().__init__(get_response)
        
        if self.auth_enabled:
            logger.info("Authentication middleware enabled")
        else:
            logger.warning("Authentication middleware disabled - not for production!")
    
    def process_request(self, request):
        """
        Process incoming request to validate authentication token
        """
        # Skip authentication if disabled (development only)
        if not self.auth_enabled:
            return None
        
        # Skip authentication for safe methods
        if request.method in self.SAFE_METHODS:
            return None
        
        # Skip authentication for excluded paths
        if self._is_excluded_path(request.path):
            logger.debug(f"Skipping auth for excluded path: {request.path}")
            return None
        
        # Get the token from headers
        auth_token = request.headers.get('X-Auth-Token') or request.META.get('HTTP_X_AUTH_TOKEN')
        
        # Validate token
        if not auth_token:
            logger.warning(
                f"Authentication failed: No token provided "
                f"[Method: {request.method}] [Path: {request.path}] "
                f"[IP: {self._get_client_ip(request)}]"
            )
            return self._unauthorized_response('Authentication token not provided')
        
        if auth_token != self.expected_token:
            logger.warning(
                f"Authentication failed: Invalid token "
                f"[Method: {request.method}] [Path: {request.path}] "
                f"[IP: {self._get_client_ip(request)}] "
                f"[Token: {auth_token[:10]}...]"
            )
            return self._unauthorized_response('Invalid authentication token')
        
        # Authentication successful
        logger.debug(
            f"Authentication successful "
            f"[Method: {request.method}] [Path: {request.path}]"
        )
        
        # Add authenticated flag to request
        request.is_authenticated = True
        
        return None
    
    def _is_excluded_path(self, path):
        """
        Check if the path should be excluded from authentication
        """
        return any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS)
    
    def _get_client_ip(self, request):
        """
        Get client IP address from request
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def _unauthorized_response(self, message):
        """
        Return 401 Unauthorized response
        """
        return JsonResponse(
            {
                'error': {
                    'code': 'unauthorized',
                    'message': message,
                }
            },
            status=status.HTTP_401_UNAUTHORIZED
        )


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log all incoming requests and outgoing responses
    """
    
    def process_request(self, request):
        """
        Log incoming request details
        """
        logger.info(
            f"Incoming Request: {request.method} {request.path} "
            f"[IP: {self._get_client_ip(request)}] "
            f"[User-Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')}]"
        )
        
        # Log request body for non-GET requests (but exclude sensitive data)
        if request.method in ['POST', 'PUT', 'PATCH'] and hasattr(request, 'body'):
            try:
                # Don't log the actual body content for security
                logger.debug(f"Request body size: {len(request.body)} bytes")
            except Exception:
                pass
        
        return None
    
    def process_response(self, request, response):
        """
        Log outgoing response details
        """
        logger.info(
            f"Outgoing Response: {request.method} {request.path} "
            f"[Status: {response.status_code}] "
            f"[IP: {self._get_client_ip(request)}]"
        )
        return response
    
    def _get_client_ip(self, request):
        """
        Get client IP address from request
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class ExceptionLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log uncaught exceptions
    """
    
    def process_exception(self, request, exception):
        """
        Log exceptions that occur during request processing
        """
        logger.error(
            f"Uncaught Exception: {exception.__class__.__name__} - {str(exception)} "
            f"[Method: {request.method}] [Path: {request.path}] "
            f"[IP: {self._get_client_ip(request)}]",
            exc_info=True
        )
        
        # Return None to let Django's default exception handling continue
        return None
    
    def _get_client_ip(self, request):
        """
        Get client IP address from request
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class CorsMiddleware(MiddlewareMixin):
    """
    Simple CORS middleware for development
    For production, use django-cors-headers package
    """
    
    def process_response(self, request, response):
        """
        Add CORS headers to response
        """
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, X-Auth-Token, Authorization'
        response['Access-Control-Max-Age'] = '3600'
        
        return response
