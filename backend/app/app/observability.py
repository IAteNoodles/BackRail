import contextvars
import logging
import uuid


_request_context = contextvars.ContextVar('request_context', default={})


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        token = _request_context.set(
            {
                'request_id': request_id,
                'request_method': request.method,
                'request_path': request.get_full_path(),
            }
        )
        request.request_id = request_id

        try:
            response = self.get_response(request)
        finally:
            _request_context.reset(token)

        response['X-Request-ID'] = request_id
        return response


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        context = _request_context.get({})
        record.request_id = context.get('request_id', '-')
        record.request_method = context.get('request_method', '-')
        record.request_path = context.get('request_path', '-')
        return True


class StaticContextFilter(logging.Filter):
    def __init__(self, service_name='railway-backend', environment='development'):
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def filter(self, record):
        record.service = self.service_name
        record.environment = self.environment
        return True