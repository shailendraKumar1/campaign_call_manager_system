"""
Logging utilities for the Campaign Call Manager System
Provides easy-to-use logging functions and decorators
"""
import logging
import functools
import time
from typing import Callable, Any


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name
    
    Args:
        name: Logger name (usually __name__ of the module)
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


def log_execution_time(logger: logging.Logger = None):
    """
    Decorator to log function execution time
    
    Usage:
        @log_execution_time(logger)
        def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)
            
            start_time = time.time()
            logger.debug(f"Starting {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"Completed {func.__name__} in {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"Failed {func.__name__} after {execution_time:.3f}s: {str(e)}")
                raise
        
        return wrapper
    return decorator


def log_api_request(logger: logging.Logger = None):
    """
    Decorator to log API request details
    
    Usage:
        @log_api_request(logger)
        def my_api_view(request):
            pass
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, request, *args, **kwargs) -> Any:
            nonlocal logger
            if logger is None:
                logger = logging.getLogger(func.__module__)
            
            method = request.method
            path = request.path
            logger.info(f"API Request: {method} {path}")
            logger.debug(f"Request data: {request.data if hasattr(request, 'data') else 'N/A'}")
            
            try:
                response = func(self, request, *args, **kwargs)
                logger.info(f"API Response: {method} {path} - Status: {response.status_code}")
                return response
            except Exception as e:
                logger.error(f"API Error: {method} {path} - {str(e)}", exc_info=True)
                raise
        
        return wrapper
    return decorator


def log_kafka_event(logger: logging.Logger, event_type: str, topic: str, data: dict):
    """
    Log Kafka event publishing
    
    Args:
        logger: Logger instance
        event_type: Type of event (e.g., 'initiate_call', 'callback')
        topic: Kafka topic name
        data: Event data dictionary
    """
    logger.info(f"Publishing Kafka event: {event_type} to topic: {topic}")
    logger.debug(f"Event data: {data}")


def log_database_operation(logger: logging.Logger, operation: str, model: str, record_id: Any = None):
    """
    Log database operations
    
    Args:
        logger: Logger instance
        operation: Operation type (CREATE, UPDATE, DELETE, etc.)
        model: Model name
        record_id: Record identifier (optional)
    """
    if record_id:
        logger.debug(f"Database {operation}: {model} [ID: {record_id}]")
    else:
        logger.debug(f"Database {operation}: {model}")


def log_call_event(logger: logging.Logger, call_id: str, event: str, details: dict = None):
    """
    Log call-related events
    
    Args:
        logger: Logger instance
        call_id: Call identifier
        event: Event description
        details: Additional event details (optional)
    """
    message = f"Call Event [{call_id}]: {event}"
    if details:
        message += f" - {details}"
    logger.info(message)


def log_error(logger: logging.Logger, error: Exception, context: str = ""):
    """
    Log error with context and stack trace
    
    Args:
        logger: Logger instance
        error: Exception instance
        context: Additional context about where the error occurred
    """
    message = f"Error in {context}: {str(error)}" if context else f"Error: {str(error)}"
    logger.error(message, exc_info=True)


def log_metric(logger: logging.Logger, metric_name: str, value: Any, unit: str = ""):
    """
    Log application metrics
    
    Args:
        logger: Logger instance
        metric_name: Name of the metric
        value: Metric value
        unit: Unit of measurement (optional)
    """
    unit_str = f" {unit}" if unit else ""
    logger.info(f"Metric: {metric_name} = {value}{unit_str}")


class LogContext:
    """
    Context manager for logging blocks of code
    
    Usage:
        with LogContext(logger, "Processing batch"):
            # Your code here
            pass
    """
    def __init__(self, logger: logging.Logger, operation: str, level: int = logging.INFO):
        self.logger = logger
        self.operation = operation
        self.level = level
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        self.logger.log(self.level, f"Starting: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        execution_time = time.time() - self.start_time
        if exc_type is None:
            self.logger.log(self.level, f"Completed: {self.operation} in {execution_time:.3f}s")
        else:
            self.logger.error(f"Failed: {self.operation} after {execution_time:.3f}s - {exc_val}")
        return False  # Don't suppress exceptions


# Example usage in module
if __name__ == "__main__":
    # Create a logger for testing
    test_logger = get_logger(__name__)
    
    # Test basic logging
    test_logger.info("This is an info message")
    test_logger.debug("This is a debug message")
    test_logger.warning("This is a warning message")
    test_logger.error("This is an error message")
    
    # Test log context
    with LogContext(test_logger, "Test operation"):
        test_logger.info("Inside context")
    
    print("Logging utilities loaded successfully!")
