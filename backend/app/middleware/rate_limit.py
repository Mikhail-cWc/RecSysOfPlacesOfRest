import logging

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute", "1000/hour"],
    storage_uri="memory://",
)


def setup_rate_limiting(app):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    logger.info("Rate limiting configured")
