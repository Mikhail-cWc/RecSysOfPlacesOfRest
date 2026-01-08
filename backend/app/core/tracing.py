import logging
from typing import Optional

from app.core.config import settings
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def init_phoenix_tracing() -> Optional[TracerProvider]:
    if not settings.PHOENIX_ENABLED:
        logger.info("Phoenix tracing disabled")
        return None

    try:
        resource = Resource.create({"service.name": settings.PHOENIX_PROJECT_NAME})

        tracer_provider = TracerProvider(resource=resource)

        otlp_exporter = OTLPSpanExporter(endpoint=settings.PHOENIX_ENDPOINT)
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)

        trace.set_tracer_provider(tracer_provider)

        logger.info(f"Phoenix tracing initialized: {settings.PHOENIX_ENDPOINT}")
        return tracer_provider

    except Exception as e:
        logger.error(f"Failed to initialize Phoenix tracing: {e}")
        return None


def instrument_langchain():
    """
    Трейсы LangChain с помощью OpenInference.

    Автоматически добавляет трейсинг для всех операций LangChain:
    - Agent вызовы
    - Tool вызовы
    - Chain executions
    - Промпты и ответы
    """
    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor

        LangChainInstrumentor().instrument()
        logger.info("LangChain instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument LangChain: {e}")


def instrument_openai():
    """
    Трейсы OpenAI с помощью OpenInference.

    Автоматически добавляет трейсинг для всех операций OpenAI:
    - LLM вызовы
    - Embedding генерация
    - Токены и стоимость
    - Latency
    """
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
        logger.info("OpenAI instrumentation enabled")
    except Exception as e:
        logger.error(f"Failed to instrument OpenAI: {e}")
