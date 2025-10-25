"""
Custom exceptions for the Campaign Call Manager System
"""
from rest_framework.exceptions import APIException
from rest_framework import status


class BadRequestException(APIException):
    """Exception for 400 Bad Request errors"""
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Invalid request parameters.'
    default_code = 'bad_request'


class UnauthorizedException(APIException):
    """Exception for 401 Unauthorized errors"""
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Authentication credentials were not provided or are invalid.'
    default_code = 'unauthorized'


class ForbiddenException(APIException):
    """Exception for 403 Forbidden errors"""
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'You do not have permission to perform this action.'
    default_code = 'forbidden'


class NotFoundException(APIException):
    """Exception for 404 Not Found errors"""
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = 'The requested resource was not found.'
    default_code = 'not_found'


class ConflictException(APIException):
    """Exception for 409 Conflict errors"""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'The request conflicts with the current state of the resource.'
    default_code = 'conflict'


class TooManyRequestsException(APIException):
    """Exception for 429 Too Many Requests errors"""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = 'Too many requests. Please try again later.'
    default_code = 'too_many_requests'


class InternalServerErrorException(APIException):
    """Exception for 500 Internal Server Error"""
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = 'An internal server error occurred. Please try again later.'
    default_code = 'internal_server_error'


class ServiceUnavailableException(APIException):
    """Exception for 503 Service Unavailable errors"""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Service temporarily unavailable. Please try again later.'
    default_code = 'service_unavailable'


# Specific business logic exceptions
class CampaignNotFoundException(NotFoundException):
    """Exception when campaign is not found"""
    default_detail = 'Campaign not found or inactive.'


class CallNotFoundException(NotFoundException):
    """Exception when call is not found"""
    default_detail = 'Call not found.'


class InvalidPhoneNumberException(BadRequestException):
    """Exception for invalid phone number format"""
    default_detail = 'Invalid phone number format.'


class DuplicateCallException(ConflictException):
    """Exception for duplicate call attempts"""
    default_detail = 'A call to this number was recently initiated. Please try again later.'


class ConcurrencyLimitException(TooManyRequestsException):
    """Exception when concurrent call limit is reached"""
    default_detail = 'Maximum concurrent calls limit reached. Please try again later.'


class InvalidCallStatusException(BadRequestException):
    """Exception for invalid call status"""
    default_detail = 'Invalid call status provided.'


class KafkaPublishException(InternalServerErrorException):
    """Exception when Kafka message publishing fails"""
    default_detail = 'Failed to publish message to message queue.'
