from django.db import OperationalError, ProgrammingError
from django.shortcuts import render


class SetupErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (OperationalError, ProgrammingError)):
            return None

        message = str(exception).lower()
        setup_markers = (
            "no such table",
            "does not exist",
            "unable to open database file",
            "connection refused",
            "could not connect to server",
            "password authentication failed",
        )
        if not any(marker in message for marker in setup_markers):
            return None

        return render(
            request,
            "ups/setup_error.html",
            {
                "error_message": str(exception),
            },
            status=503,
        )
