class Dhis2Error(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class Dhis2AuthError(Dhis2Error):
    def __init__(self, message: str = "DHIS2 authentication failed.") -> None:
        super().__init__("dhis2_auth_failed", message, retryable=False)


class Dhis2TimeoutError(Dhis2Error):
    def __init__(self, message: str = "DHIS2 request timed out.") -> None:
        super().__init__("dhis2_timeout", message, retryable=True)


class Dhis2TransientError(Dhis2Error):
    def __init__(self, message: str = "DHIS2 returned a transient error.") -> None:
        super().__init__("dhis2_transient", message, retryable=True)


class Dhis2ValidationError(Dhis2Error):
    def __init__(self, message: str = "DHIS2 response failed validation.") -> None:
        super().__init__("dhis2_invalid_response", message, retryable=False)


class Dhis2NotConfiguredError(Dhis2Error):
    def __init__(self) -> None:
        super().__init__(
            "dhis2_not_configured",
            "DHIS2 is not configured. Live verification is pending authorised credentials.",
            retryable=False,
        )


class Dhis2CancelledError(Dhis2Error):
    def __init__(self) -> None:
        super().__init__("dhis2_cancelled", "The DHIS2 request was cancelled.", retryable=False)


class Dhis2BoundExceededError(Dhis2Error):
    def __init__(self, message: str = "DHIS2 response exceeded the configured size bound.") -> None:
        super().__init__("dhis2_bound_exceeded", message, retryable=False)


class Dhis2PageLimitError(Dhis2Error):
    def __init__(self, message: str = "Configured DHIS2 page limit was reached before completion.") -> None:
        super().__init__("dhis2_page_limit", message, retryable=False)
