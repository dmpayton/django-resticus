import base64

from django.conf import settings
from django.contrib import auth
from django.core.exceptions import ImproperlyConfigured
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.encoding import DjangoUnicodeDecodeError
from django.utils.translation import gettext as _

from . import exceptions
from .compat import get_model, get_user_model, smart_text
from .http import HTTP_HEADER_ENCODING, Http200
from .settings import api_settings


__all__ = ["SessionAuth", "BasicHttpAuth", "SessionAuthEndpoint", "login_required"]


def get_authorization_header(request):
    """
    Return request's 'Authorization:' header, as a bytestring.
    Hide some test client ickyness where the header can be unicode.
    """
    authorization = request.META.get("HTTP_AUTHORIZATION", b"")
    if isinstance(authorization, type("")):
        # Work around django test client oddness
        authorization = authorization.encode(HTTP_HEADER_ENCODING)
    return authorization


class CSRFCheck(CsrfViewMiddleware):
    def __init__(self):
        super().__init__(lambda request: None)

    def _reject(self, request, reason):
        return reason


class BaseAuth(object):
    def authenticate(self, request):
        pass

    def authenticate_header(self, request):
        pass


class SessionAuth(BaseAuth):
    def authenticate(self, request):
        user = getattr(request, "user", None)

        if not user:
            return

        if user.is_authenticated and not user.is_active:
            raise exceptions.AuthenticationFailed(_("User inactive or deleted."))

        self.enforce_csrf(request)
        return user

    def enforce_csrf(self, request):
        check = CSRFCheck()
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.Forbidden(_("CSRF Failed: {0}").format(reason))


class BasicHttpAuth(BaseAuth):
    www_authenticate_realm = "api"

    def authenticate(self, request):
        authdata = get_authorization_header(request).split()

        if not authdata or authdata[0].lower() != b"basic":
            return

        if len(authdata) == 1:
            msg = _("Invalid basic header. No credentials provided.")
            raise exceptions.AuthenticationFailed(msg)
        elif len(authdata) > 2:
            msg = _(
                "Invalid basic header. Credentials string should not contain spaces."
            )
            raise exceptions.AuthenticationFailed(msg)

        try:
            auth_parts = (
                base64.b64decode(authdata[1])
                .decode(HTTP_HEADER_ENCODING)
                .partition(":")
            )
        except Exception:
            msg = _("Invalid basic header. Credentials not correctly base64 encoded.")
            raise exceptions.AuthenticationFailed(msg)

        userid, password = auth_parts[0], auth_parts[2]
        return self.authenticate_credentials(request, userid, password)

    def authenticate_credentials(self, request, userid, password):
        username_field = getattr(get_user_model(), "USERNAME_FIELD", "username")
        credentials = {username_field: userid, "password": password}

        user = auth.authenticate(**credentials)

        if user is None:
            raise exceptions.AuthenticationFailed(_("Invalid username/password."))

        if not user.is_active:
            raise exceptions.AuthenticationFailed(_("User inactive or deleted."))

        return user

    def authenticate_header(self, request):
        return 'Basic realm="{0}"'.format(self.www_authenticate_realm)


class TokenAuth(BaseAuth):
    def authenticate(self, request):
        authdata = get_authorization_header(request).split()

        if not authdata or authdata[0].lower() != b"token":
            return

        if len(authdata) == 1:
            msg = _("Invalid token header. No credentials provided.")
            raise exceptions.AuthenticationFailed(msg)
        elif len(authdata) > 2:
            msg = _("Invalid token header. Token string should not contain spaces.")
            raise exceptions.AuthenticationFailed(msg)

        return self.authenticate_credentials(request, authdata[1])

    @staticmethod
    def get_token_model():
        if api_settings.TOKEN_MODEL is None:
            msg = _(
                'You must set `RESTICUS["TOKEN_MODEL"]` in your settings '
                "to use TokenAuth."
            )
            raise ImproperlyConfigured(msg)
        return get_model(api_settings.TOKEN_MODEL)

    def lookup_user(self, request, key):
        User = get_user_model()
        encoding = request.encoding or settings.DEFAULT_CHARSET
        try:
            return User.objects.get(api_token__key=key.decode(encoding))
        except User.DoesNotExist:
            raise exceptions.AuthenticationFailed(_("Invalid token."))

    def authenticate_credentials(self, request, key):
        user = self.lookup_user(request, key)

        if not user.is_active:
            raise exceptions.AuthenticationFailed(_("User inactive or deleted."))

        return user

    def authenticate_header(self, request):
        return "Token"


def login_required(fn):
    """
    Decorator for :py:class:`resticus.views.Endpoint` methods to require
    authenticated user. This simply sets the `login_required` attribute to
    be handled by the authenticate method of :py:class:`resticus.views.Endpoint`.
    """
    fn.login_required = True
    return fn
