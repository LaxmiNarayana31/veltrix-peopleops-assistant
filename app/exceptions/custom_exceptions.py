from app.core.status_codes import ErrorCode, StatusCode


class AppException(Exception):
    """Base application exception carrying message, HTTP status code and machine error code."""

    def __init__(
        self,
        message: str,
        status_code: int = StatusCode.INTERNAL_SERVER_ERROR,
        error_code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR,
    ) -> None:
        """Initialize AppException with detail message, status code, and machine error code."""
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class BadRequestException(AppException):
    """Raised when request payload or syntax is invalid."""

    def __init__(self, message: str = "Bad request", error_code: ErrorCode = ErrorCode.BAD_REQUEST) -> None:
        """Initialize BadRequestException."""
        super().__init__(message, StatusCode.BAD_REQUEST, error_code)


class UnauthorizedException(AppException):
    """Raised when authentication credentials or headers are missing or invalid."""
    def __init__(self, message: str = "Unauthorized", error_code: ErrorCode = ErrorCode.UNAUTHORIZED) -> None:
        """Initialize UnauthorizedException."""
        super().__init__(message, StatusCode.UNAUTHORIZED, error_code)


class ForbiddenException(AppException):
    """Raised when caller is not allowed to access the requested resource or session."""
    def __init__(self, message: str = "Forbidden", error_code: ErrorCode = ErrorCode.FORBIDDEN) -> None:
        """Initialize ForbiddenException."""
        super().__init__(message, StatusCode.FORBIDDEN, error_code)


class NotFoundException(AppException):
    """Raised when requested entity is not found."""
    def __init__(self, message: str = "Not found", error_code: ErrorCode = ErrorCode.NOT_FOUND) -> None:
        """Initialize NotFoundException."""
        super().__init__(message, StatusCode.NOT_FOUND, error_code)


class ConflictException(AppException):
    """Raised when resource conflict occurs."""
    def __init__(self, message: str = "Conflict", error_code: ErrorCode = ErrorCode.CONFLICT) -> None:
        """Initialize ConflictException."""
        super().__init__(message, StatusCode.CONFLICT, error_code)


class ValidationException(AppException):
    """Raised when validation rules fail."""
    def __init__(self, message: str = "Validation error", error_code: ErrorCode = ErrorCode.VALIDATION_ERROR) -> None:
        """Initialize ValidationException."""
        super().__init__(message, StatusCode.BAD_REQUEST, error_code)


class ExtractionException(AppException):
    """Raised when text or rule extraction fails."""
    def __init__(self, message: str = "Extraction error", error_code: ErrorCode = ErrorCode.EXTRACTION_ERROR) -> None:
        """Initialize ExtractionException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class OcrException(AppException):
    """Raised when optical character recognition processing fails."""
    def __init__(self, message: str = "OCR error", error_code: ErrorCode = ErrorCode.OCR_ERROR) -> None:
        """Initialize OcrException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class DatabaseException(AppException):
    """Raised when database operation encounters an error."""
    def __init__(self, message: str = "Database error", error_code: ErrorCode = ErrorCode.DATABASE_ERROR) -> None:
        """Initialize DatabaseException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class FileFormatException(AppException):
    """Raised when encountering an unsupported or corrupt file format."""
    def __init__(self, message: str = "Unsupported or invalid file format", error_code: ErrorCode = ErrorCode.FILE_FORMAT_ERROR) -> None:
        """Initialize FileFormatException."""
        super().__init__(message, StatusCode.BAD_REQUEST, error_code)


class LlmProviderException(AppException):
    """Raised when LLM provider encounters an error."""
    def __init__(self, message: str = "LLM provider error", error_code: ErrorCode = ErrorCode.LLM_PROVIDER_ERROR) -> None:
        """Initialize LlmProviderException."""
        super().__init__(message, StatusCode.BAD_GATEWAY, error_code)


class RateLimitException(AppException):
    """Raised when upstream API or internal rate limit is exceeded."""
    def __init__(self, message: str = "Rate limit exceeded", error_code: ErrorCode = ErrorCode.RATE_LIMIT_EXCEEDED) -> None:
        """Initialize RateLimitException."""
        super().__init__(message, StatusCode.TOO_MANY_REQUESTS, error_code)


class TokenBudgetExceededException(AppException):
    """Raised when context token budget exceeds allowed limit."""
    def __init__(self, message: str = "Token budget exceeded", error_code: ErrorCode = ErrorCode.TOKEN_BUDGET_EXCEEDED) -> None:
        """Initialize TokenBudgetExceededException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class RetrievalException(AppException):
    """Raised when retrieval operations fail."""
    def __init__(self, message: str = "Retrieval error", error_code: ErrorCode = ErrorCode.RETRIEVAL_ERROR) -> None:
        """Initialize RetrievalException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class IngestionException(AppException):
    """Raised when corpus ingestion fails."""
    def __init__(self, message: str = "Ingestion error", error_code: ErrorCode = ErrorCode.INGESTION_ERROR) -> None:
        """Initialize IngestionException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class PermissionDeniedException(AppException):
    """Raised when an operation is rejected due to role or scope permissions."""
    def __init__(self, message: str = "Permission denied", error_code: ErrorCode = ErrorCode.PERMISSION_DENIED) -> None:
        """Initialize PermissionDeniedException."""
        super().__init__(message, StatusCode.FORBIDDEN, error_code)


class LeaveRuleViolationException(AppException):
    """Raised when a leave operation violates business rules."""
    def __init__(self, message: str = "Leave rule violation", error_code: ErrorCode = ErrorCode.LEAVE_RULE_VIOLATION) -> None:
        """Initialize LeaveRuleViolationException."""
        super().__init__(message, StatusCode.BAD_REQUEST, error_code)


class ConfigurationException(AppException):
    """Raised when environment or system configuration is invalid or missing."""
    def __init__(self, message: str = "Configuration error", error_code: ErrorCode = ErrorCode.CONFIGURATION_ERROR) -> None:
        """Initialize ConfigurationException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)


class InternalServerException(AppException):
    """Raised for general unhandled internal server failures."""
    def __init__(self, message: str = "Internal server error", error_code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR) -> None:
        """Initialize InternalServerException."""
        super().__init__(message, StatusCode.INTERNAL_SERVER_ERROR, error_code)
