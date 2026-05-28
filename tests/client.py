from django.conf import settings
from django.http import StreamingHttpResponse
from django.test.client import Client, MULTIPART_CONTENT
from django.test.utils import override_settings
from django.urls import reverse

from resticus.compat import json


def debug(fn):
    return override_settings(DEBUG=True)(fn)


class ApiClient(Client):
    @staticmethod
    def process(response):
        if isinstance(response, StreamingHttpResponse):
            content = ''.join([x.decode('utf-8') for x in response.streaming_content])
        else:
            content = response.content.decode('utf-8')

        if response['Content-Type'].startswith('application/json'):
            response.json = json.loads(content)
        else:
            response.json = None

        if response.status_code == 500 and settings.DEBUG:
            try:
                print(response.json['errors'][0]['meta']['traceback'])
            except Exception:
                print(response.content)

        return response

    def get(self, url_name, data={}, follow=False, extra={}, *args, **kwargs):
        return self.process(
            super(ApiClient, self).get(
                reverse(url_name, args=args, kwargs=kwargs),
                data=data,
                follow=follow,
                **extra))

    def post(self, url_name, data={}, content_type=MULTIPART_CONTENT,
            follow=False, extra={}, *args, **kwargs):
        return self.process(
            super(ApiClient, self).post(
                reverse(url_name, args=args, kwargs=kwargs),
                content_type=content_type,
                data=data,
                follow=follow,
                **extra))

    def put(self, url_name, data={}, content_type=MULTIPART_CONTENT,
            follow=False, extra={}, *args, **kwargs):
        return self.process(
            super(ApiClient, self).put(
                reverse(url_name, args=args, kwargs=kwargs),
                content_type=content_type, data=data, follow=follow, **extra))

    def delete(self, url_name, data={}, content_type=MULTIPART_CONTENT,
            follow=False, extra={}, *args, **kwargs):
        return self.process(
            super(ApiClient, self).delete(
                reverse(url_name, args=args, kwargs=kwargs),
                content_type=content_type, data=data, follow=follow, **extra))
