"""
Custom exception handler for REST framework
Provides consistent error responses across the API
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import Http404
from django.db import IntegrityError

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that provides consistent error responses
    
    Returns:
        Response with error details in a consistent format:
        {
            "error": {
                "code": "error_code",
                "message": "Error message",
                "details": {...}  # Optional additional details
            }
        }
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    # Get the view and request from context
    view = context.get('view', None)
    request = context.get('request', None)
    
    # Log the exception
    if response is not None:
        logger.warning(
            f"API Exception: {exc.__class__.__name__} - {str(exc)} "
            f"[Status: {response.status_code}] "
            f"[View: {view.__class__.__name__ if view else 'Unknown'}] "
            f"[Path: {request.path if request else 'Unknown'}]"
        )
    else:
        logger.error(
            f"Unhandled Exception: {exc.__class__.__name__} - {str(exc)} "
            f"[View: {view.__class__.__name__ if view else 'Unknown'}] "
            f"[Path: {request.path if request else 'Unknown'}]",
            exc_info=True
        )
    
    # If response is None, handle Django exceptions
    if response is None:
        response = handle_django_exceptions(exc, context)
    
    # Format the response
    if response is not None:
        error_code = get_error_code(exc, response.status_code)
        error_message = get_error_message(exc, response)
        
        # Build standardized error response
        error_response = {
            'error': {
                'code': error_code,
                'message': error_message,
            }
        }
        
        # Add details if available
        if hasattr(response, 'data') and response.data:
            # If data is a dict with multiple fields, add as details
            if isinstance(response.data, dict) and len(response.data) > 0:
                # Check if it's validation errors
                if all(isinstance(v, list) for v in response.data.values()):
                    error_response['error']['details'] = response.data
                else:
                    # Merge into the error response
                    if 'detail' in response.data:
                        error_response['error']['message'] = str(response.data['detail'])
                    elif response.data != error_response['error']:
                        error_response['error']['details'] = response.data
        
        # Add request ID if available
        if request and hasattr(request, 'id'):
            error_response['error']['request_id'] = request.id
        
        response.data = error_response
    
    return response


def handle_django_exceptions(exc, context):
    """
    Handle Django core exceptions that aren't handled by DRF
    """
    request = context.get('request', None)
    
    # Handle Django's Http404
    if isinstance(exc, Http404):
        return Response(
            {
                'error': {
                    'code': 'not_found',
                    'message': 'The requested resource was not found.',
                }
            },
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Handle Django's PermissionDenied
    if isinstance(exc, PermissionDenied):
        return Response(
            {
                'error': {
                    'code': 'forbidden',
                    'message': 'You do not have permission to perform this action.',
                }
            },
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Handle Django's ValidationError
    if isinstance(exc, ValidationError):
        return Response(
            {
                'error': {
                    'code': 'validation_error',
                    'message': 'Validation failed.',
                    'details': exc.message_dict if hasattr(exc, 'message_dict') else {'error': exc.messages}
                }
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Handle Database IntegrityError
    if isinstance(exc, IntegrityError):
        return Response(
            {
                'error': {
                    'code': 'integrity_error',
                    'message': 'Database integrity constraint violation.',
                    'details': str(exc)
                }
            },
            status=status.HTTP_409_CONFLICT
        )
    
    # Handle all other exceptions as 500 Internal Server Error
    logger.error(
        f"Unhandled exception: {exc.__class__.__name__} - {str(exc)}",
        exc_info=True,
        extra={'request': request}
    )
    
    return Response(
        {
            'error': {
                'code': 'internal_server_error',
                'message': 'An internal server error occurred. Please try again later.',
            }
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


def get_error_code(exc, status_code):
    """
    Get error code from exception or generate from status code
    """
    if hasattr(exc, 'default_code'):
        return exc.default_code
    
    # Map status codes to error codes
    code_mapping = {
        400: 'bad_request',
        401: 'unauthorized',
        403: 'forbidden',
        404: 'not_found',
        409: 'conflict',
        429: 'too_many_requests',
        500: 'internal_server_error',
        503: 'service_unavailable',
    }
    
    return code_mapping.get(status_code, 'error')


def get_error_message(exc, response):
    """
    Get error message from exception
    """
    # Try to get detail from exception
    if hasattr(exc, 'detail'):
        detail = exc.detail
        if isinstance(detail, str):
            return detail
        elif isinstance(detail, dict) and 'detail' in detail:
            return str(detail['detail'])
        elif isinstance(detail, list) and len(detail) > 0:
            return str(detail[0])
    
    # Try to get from response data
    if hasattr(response, 'data') and response.data:
        if isinstance(response.data, dict):
            if 'detail' in response.data:
                return str(response.data['detail'])
            elif 'message' in response.data:
                return str(response.data['message'])
    
    # Default message
    return str(exc)
