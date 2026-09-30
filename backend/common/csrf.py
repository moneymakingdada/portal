from rest_framework.authentication import SessionAuthentication


class EnforceCsrfMixin:
    """Verify the CSRF token on every state-changing request.

    DRF only checks CSRF for requests that already carry a session, so endpoints
    reachable while logged out (login, sign-up) would otherwise skip it.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
            SessionAuthentication().enforce_csrf(request)
