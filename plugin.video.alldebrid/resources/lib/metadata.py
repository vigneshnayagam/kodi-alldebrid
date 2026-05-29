import re
import json
import time
import urllib.request
import urllib.parse
import xbmcaddon
import xbmcvfs
from .constants import TMDB_API_BASE, TMDB_IMAGE_BASE, DEFAULT_TMDB_API_KEY
from .utils import debug_trace


NOISE_PATTERN = re.compile(
    r'[\.\s\-_]?('
    r'2160p|1080p|720p|480p|360p|4k|uhd|'
    r'bluray|blu[\.\-]?ray|bdrip|brrip|remux|'
    r'web[\.\-]?dl|webrip|web[\.\-]?rip|hdtv|hdrip|dvdrip|dvdscr|cam|ts|'
    r'x264|x265|h\.?264|h\.?265|hevc|avc|xvid|divx|'
    r'aac|ac3|dts|dts[\.\-]?hd|atmos|truehd|flac|mp3|eac3|'
    r'hdr|hdr10|hdr10\+|dolby[\.\-]?vision|dv|sdr|'
    r'10bit|8bit|'
    r'multi|dual[\.\-]?audio|'
    r'repack|proper|extended|unrated|directors[\.\-]?cut|'
    r'nf|amzn|dsnp|hmax|atvp|pcok|hulu|'
    r'complete|season[\.\-]?pack'
    r')[\.\s\-_]?',
    re.IGNORECASE,
)

GROUP_PATTERN = re.compile(r'[\-\.]([a-zA-Z0-9]+)$')

TV_PATTERN = re.compile(
    r'[.\s\-_](?:S(\d{1,2})E(\d{1,2})|(\d{1,2})x(\d{2,3}))[.\s\-_]?',
    re.IGNORECASE,
)

YEAR_PATTERN = re.compile(r'[.\s\-_\(]?((?:19|20)\d{2})[.\s\-_\)]?')


def parse_filename(filename):
    name = filename
    ext_pos = name.rfind('.')
    if ext_pos > 0:
        ext = name[ext_pos:].lower()
        if len(ext) <= 5:
            name = name[:ext_pos]

    result = {
        'title': '',
        'year': None,
        'season': None,
        'episode': None,
        'media_type': 'movie',
    }

    tv_match = TV_PATTERN.search(name)
    if tv_match:
        if tv_match.group(1) is not None:
            result['season'] = int(tv_match.group(1))
            result['episode'] = int(tv_match.group(2))
        else:
            result['season'] = int(tv_match.group(3))
            result['episode'] = int(tv_match.group(4))
        result['media_type'] = 'tvshow'
        name = name[:tv_match.start()]

    year_match = YEAR_PATTERN.search(name)
    if year_match:
        result['year'] = int(year_match.group(1))
        name = name[:year_match.start()]

    name = NOISE_PATTERN.sub(' ', name)
    name = GROUP_PATTERN.sub('', name)
    name = re.sub(r'[.\-_]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'\s*[\(\[\{].*?[\)\]\}]\s*', ' ', name).strip()

    result['title'] = name
    return result


class TMDBClient:

    def __init__(self, api_key=None):
        if not api_key:
            addon = xbmcaddon.Addon()
            api_key = addon.getSetting('tmdb_api_key') or DEFAULT_TMDB_API_KEY
        self._api_key = api_key
        self._cache = _load_cache()

    def _request(self, path, params=None):
        params = params or {}
        params['api_key'] = self._api_key
        url = f'{TMDB_API_BASE}{path}?{urllib.parse.urlencode(params)}'
        debug_trace(f'TMDB request: {path}')
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode('utf-8'))

    def _cached(self, cache_key, fetcher):
        entry = self._cache.get(cache_key)
        if entry and entry.get('expires', 0) > time.time():
            return entry['data']
        data = fetcher()
        self._cache[cache_key] = {
            'data': data,
            'expires': time.time() + 30 * 86400,
        }
        _save_cache(self._cache)
        return data

    def search_movie(self, title, year=None):
        params = {'query': title}
        if year:
            params['year'] = year

        def fetch():
            resp = self._request('/search/movie', params)
            results = resp.get('results', [])
            return results[0] if results else None

        key = f'movie:{title}:{year or ""}'
        return self._cached(key, fetch)

    def search_tv(self, title, year=None):
        params = {'query': title}
        if year:
            params['first_air_date_year'] = year

        def fetch():
            resp = self._request('/search/tv', params)
            results = resp.get('results', [])
            return results[0] if results else None

        key = f'tv:{title}:{year or ""}'
        return self._cached(key, fetch)

    def get_movie_details(self, movie_id):
        def fetch():
            return self._request(f'/movie/{movie_id}', {'append_to_response': 'credits'})

        return self._cached(f'movie_detail:{movie_id}', fetch)

    def get_tv_details(self, tv_id):
        def fetch():
            return self._request(f'/tv/{tv_id}', {'append_to_response': 'credits'})

        return self._cached(f'tv_detail:{tv_id}', fetch)

    def get_episode_details(self, tv_id, season, episode):
        def fetch():
            return self._request(f'/tv/{tv_id}/season/{season}/episode/{episode}')

        return self._cached(f'ep:{tv_id}:{season}:{episode}', fetch)

    def get_image_url(self, path, size='w500'):
        if not path:
            return ''
        return f'{TMDB_IMAGE_BASE}/{size}{path}'


def _cache_path():
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    xbmcvfs.mkdirs(profile)
    return profile + 'tmdb_cache.json'


def _load_cache():
    path = _cache_path()
    if not xbmcvfs.exists(path):
        return {}
    try:
        f = xbmcvfs.File(path, 'r')
        data = f.read()
        f.close()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _save_cache(cache):
    try:
        now = time.time()
        cache = {k: v for k, v in cache.items() if v.get('expires', 0) > now}
        f = xbmcvfs.File(_cache_path(), 'w')
        f.write(json.dumps(cache))
        f.close()
    except Exception:
        pass
