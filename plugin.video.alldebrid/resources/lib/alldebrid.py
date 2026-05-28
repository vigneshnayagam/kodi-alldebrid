import json
import time
import urllib.request
import urllib.parse
import urllib.error
from .constants import API_BASE, AGENT
from .utils import log


class AllDebridError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f'{code}: {message}')


class AllDebridAPI:
    def __init__(self, api_key=''):
        self.api_key = api_key

    def _url(self, path, version='v4'):
        return f'{API_BASE}/{version}/{path}'

    def _request(self, method, path, params=None, data=None, version='v4', auth=True):
        if params is None:
            params = {}
        params['agent'] = AGENT

        url = self._url(path, version)
        if method == 'GET' or (method == 'POST' and not data):
            query = urllib.parse.urlencode(params, doseq=True)
            url = f'{url}?{query}'

        log(f'{method} {url}')

        if method == 'POST' and data:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f'{url}?{query}'
            encoded_data = urllib.parse.urlencode(data, doseq=True).encode('utf-8')
            req = urllib.request.Request(url, data=encoded_data, method='POST')
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        else:
            req = urllib.request.Request(url, method=method)

        if auth and self.api_key:
            req.add_header('Authorization', f'Bearer {self.api_key}')

        retry_delays = [1, 3, 5]
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode('utf-8'))

                if body.get('status') == 'error':
                    err = body.get('error', {})
                    raise AllDebridError(
                        err.get('code', 'UNKNOWN'),
                        err.get('message', 'Unknown error'),
                    )

                return body.get('data', {})

            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 2:
                    log(f'Rate limited (HTTP {e.code}), retry in {retry_delays[attempt]}s')
                    time.sleep(retry_delays[attempt])
                    continue
                try:
                    error_body = json.loads(e.read().decode('utf-8'))
                    err = error_body.get('error', {})
                    raise AllDebridError(
                        err.get('code', f'HTTP_{e.code}'),
                        err.get('message', e.reason),
                    )
                except (json.JSONDecodeError, AttributeError):
                    raise AllDebridError(f'HTTP_{e.code}', e.reason)

            except urllib.error.URLError as e:
                if attempt < 2:
                    time.sleep(retry_delays[attempt])
                    continue
                raise AllDebridError('NETWORK_ERROR', str(e.reason))

    def _get(self, path, params=None, version='v4', auth=True):
        return self._request('GET', path, params=params, version=version, auth=auth)

    def _post(self, path, params=None, data=None, version='v4', auth=True):
        return self._request('POST', path, params=params, data=data, version=version, auth=auth)

    # --- PIN Auth (no auth required) ---

    def pin_get(self):
        return self._get('pin/get', auth=False)

    def pin_check(self, check, pin):
        return self._get('pin/check', params={'check': check, 'pin': pin}, auth=False)

    # --- User ---

    def get_user(self):
        return self._get('user')

    def get_user_links(self):
        data = self._get('user/links')
        return data.get('links', [])

    # --- Magnets ---

    def get_magnets(self, status_filter=None):
        params = {}
        if status_filter:
            params['status'] = status_filter
        data = self._get('magnet/status', params=params)
        return data.get('magnets', [])

    def get_magnet(self, magnet_id):
        data = self._get('magnet/status', params={'id': magnet_id})
        return data.get('magnets', {})

    def get_magnet_files(self, magnet_id):
        data = self._get('magnet/files', params={'id[]': magnet_id})
        files_data = data.get('files', [])
        if files_data and isinstance(files_data, list):
            first = files_data[0]
            return first.get('files', first.get('e', []))
        return files_data

    def upload_magnet(self, magnet_uri):
        return self._post('magnet/upload', data={'magnets[]': magnet_uri})

    def delete_magnet(self, magnet_id):
        return self._get('magnet/delete', params={'id': magnet_id})

    def restart_magnet(self, magnet_id):
        return self._get('magnet/restart', params={'id': magnet_id})

    # --- Links ---

    def unlock_link(self, link):
        return self._get('link/unlock', params={'link': link})

    def get_streaming_link(self, gen_id, stream_id):
        return self._get('link/streaming', params={'id': gen_id, 'stream': stream_id})

    def check_delayed(self, delayed_id):
        return self._get('link/delayed', params={'id': delayed_id})
