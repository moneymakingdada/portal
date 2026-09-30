class ApiError(Exception):
    """A predictable, user-facing API failure.

    Rendered by common.exceptions.api_exception_handler as
        {"error": {"code": ..., "message": ..., **extra}}
    """

    def __init__(self, code: str, message: str, status: int = 400, *, retry_after: int | None = None, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retry_after = retry_after
        self.extra = extra

    def payload(self) -> dict:
        body = {"code": self.code, "message": self.message, **self.extra}
        if self.retry_after is not None:
            body["retry_after"] = self.retry_after
        return body
