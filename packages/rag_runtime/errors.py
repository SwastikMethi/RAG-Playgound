from dataclasses import dataclass, field


@dataclass
class Problem(Exception):
    code: str
    message: str
    status: int = 422
    retryable: bool = False
    details: dict = field(default_factory=dict)

    def __str__(self):
        return self.message

    def public(self, request_id=None):
        return dict(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
            request_id=request_id,
        )
