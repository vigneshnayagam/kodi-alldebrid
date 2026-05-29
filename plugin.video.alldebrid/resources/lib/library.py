import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from .metadata import parse_filename, TMDBClient, TMDBAuthError
from .utils import is_video_file, debug_trace, notify

PLUGIN_ID = 'plugin.video.alldebrid'


class LibrarySync:

    def __init__(self, api):
        self._api = api
        addon = xbmcaddon.Addon()
        profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
        xbmcvfs.mkdirs(profile)
        self._manifest_path = profile + 'library_manifest.json'
        self._movies_path = addon.getSetting('library_movies_path')
        if not self._movies_path:
            self._movies_path = xbmcvfs.translatePath('special://profile/strm/Movies')
        else:
            self._movies_path = xbmcvfs.translatePath(self._movies_path)
        self._tvshows_path = addon.getSetting('library_tvshows_path')
        if not self._tvshows_path:
            self._tvshows_path = xbmcvfs.translatePath('special://profile/strm/TVShows')
        else:
            self._tvshows_path = xbmcvfs.translatePath(self._tvshows_path)
        self._tmdb = TMDBClient()
        self._manifest = self._load_manifest()
        self._tmdb_warned = False

    def _warn_tmdb_auth(self):
        if not self._tmdb_warned:
            notify('TMDB API key invalid - set your own in Settings > Library', icon='error')
            self._tmdb_warned = True

    def sync_magnet(self, magnet_id):
        debug_trace(f'=== SYNC magnet {magnet_id} ===')
        try:
            files = self._api.get_magnet_files(magnet_id)
        except Exception as e:
            debug_trace(f'sync failed to get files: {e}')
            notify(f'Sync failed: {e}', icon='error')
            return False

        videos = self._collect_video_files(files)
        if not videos:
            notify('No video files found in this magnet.')
            return False

        progress = xbmcgui.DialogProgress()
        progress.create('Syncing to Library', f'Processing {len(videos)} file(s)...')
        synced_files = []

        for i, vf in enumerate(videos):
            if progress.iscanceled():
                break
            filename = vf.get('n', '')
            link = vf.get('l', '')
            pct = int((i / len(videos)) * 100)
            progress.update(pct, f'Processing: {filename}')

            result = self._process_video(filename, link)
            if result:
                synced_files.append(result)

        progress.close()

        self._manifest[str(magnet_id)] = {
            'synced_at': int(time.time()),
            'files': synced_files,
        }
        self._save_manifest()

        if synced_files:
            notify(f'Synced {len(synced_files)} file(s) to library')
            xbmc.executebuiltin('UpdateLibrary(video)')

        return True

    def sync_all(self):
        debug_trace('=== SYNC ALL magnets ===')
        try:
            magnets = self._api.get_magnets()
        except Exception as e:
            debug_trace(f'sync_all failed: {e}')
            notify(f'Sync failed: {e}', icon='error')
            return

        ready = [m for m in magnets if m.get('statusCode') == 4]
        if not ready:
            notify('No ready magnets to sync.')
            return

        new_magnets = [m for m in ready if str(m.get('id')) not in self._manifest]
        if not new_magnets:
            notify('All magnets already synced.')
            return

        debug_trace(f'{len(new_magnets)} new magnets to sync')
        count = 0
        for m in new_magnets:
            if self.sync_magnet(m['id']):
                count += 1

        if count > 0:
            notify(f'Synced {count} magnet(s) to library')

    def remove_synced_magnet(self, magnet_id):
        key = str(magnet_id)
        entry = self._manifest.get(key)
        if not entry:
            return
        for f in entry.get('files', []):
            for path_key in ('strm', 'nfo'):
                path = f.get(path_key, '')
                if path and xbmcvfs.exists(path):
                    xbmcvfs.delete(path)
        del self._manifest[key]
        self._save_manifest()
        xbmc.executebuiltin('CleanLibrary(video, false)')

    def _process_video(self, filename, link):
        parsed = parse_filename(filename)
        title = parsed['title']
        if not title:
            debug_trace(f'could not parse title from: {filename}')
            return None

        strm_url = f'plugin://{PLUGIN_ID}/?action=play&link={quote_plus(link)}'

        if parsed['media_type'] == 'tvshow':
            return self._sync_tvshow(parsed, strm_url, link)
        else:
            return self._sync_movie(parsed, strm_url, link)

    def _sync_movie(self, parsed, strm_url, link):
        title = parsed['title']
        year = parsed['year']

        tmdb_data = None
        try:
            tmdb_data = self._tmdb.search_movie(title, year)
        except TMDBAuthError:
            self._warn_tmdb_auth()
        except Exception as e:
            debug_trace(f'TMDB search failed for "{title}": {e}')

        if tmdb_data and not year:
            release = tmdb_data.get('release_date', '')
            if release:
                year = int(release[:4])

        folder_name = f'{title} ({year})' if year else title
        folder_name = _safe_filename(folder_name)
        folder = self._movies_path + '/' + folder_name + '/'
        xbmcvfs.mkdirs(folder)

        strm_path = folder + folder_name + '.strm'
        self._write_file(strm_path, strm_url)

        nfo_path = folder + folder_name + '.nfo'
        if tmdb_data:
            details = None
            try:
                details = self._tmdb.get_movie_details(tmdb_data['id'])
            except Exception as e:
                debug_trace(f'TMDB details failed: {e}')
            self._write_movie_nfo(nfo_path, tmdb_data, details)
        else:
            self._write_basic_nfo(nfo_path, 'movie', title, year)

        debug_trace(f'synced movie: {strm_path}')
        return {'strm': strm_path, 'nfo': nfo_path, 'link': link}

    def _sync_tvshow(self, parsed, strm_url, link):
        title = parsed['title']
        season = parsed.get('season', 1)
        episode = parsed.get('episode', 1)
        year = parsed['year']

        tmdb_data = None
        try:
            tmdb_data = self._tmdb.search_tv(title, year)
        except TMDBAuthError:
            self._warn_tmdb_auth()
        except Exception as e:
            debug_trace(f'TMDB TV search failed for "{title}": {e}')

        show_name = _safe_filename(title)
        show_dir = self._tvshows_path + '/' + show_name + '/'
        season_dir = show_dir + f'Season {season}/'
        xbmcvfs.mkdirs(season_dir)

        tvshow_nfo = show_dir + 'tvshow.nfo'
        if not xbmcvfs.exists(tvshow_nfo) and tmdb_data:
            tv_details = None
            try:
                tv_details = self._tmdb.get_tv_details(tmdb_data['id'])
            except Exception:
                pass
            self._write_tvshow_nfo(tvshow_nfo, tmdb_data, tv_details)
        elif not xbmcvfs.exists(tvshow_nfo):
            self._write_basic_nfo(tvshow_nfo, 'tvshow', title, year)

        ep_name = f'S{season:02d}E{episode:02d}'
        strm_path = season_dir + ep_name + '.strm'
        self._write_file(strm_path, strm_url)

        nfo_path = season_dir + ep_name + '.nfo'
        ep_data = None
        if tmdb_data:
            try:
                ep_data = self._tmdb.get_episode_details(tmdb_data['id'], season, episode)
            except Exception as e:
                debug_trace(f'TMDB episode details failed: {e}')
        self._write_episode_nfo(nfo_path, parsed, tmdb_data, ep_data)

        debug_trace(f'synced episode: {strm_path}')
        return {'strm': strm_path, 'nfo': nfo_path, 'link': link}

    def _write_movie_nfo(self, path, search_data, details=None):
        root = ET.Element('movie')
        _add_text(root, 'title', search_data.get('title', ''))
        _add_text(root, 'originaltitle', search_data.get('original_title', ''))
        release = search_data.get('release_date', '')
        if release:
            _add_text(root, 'year', release[:4])
        _add_text(root, 'plot', search_data.get('overview', ''))
        _add_text(root, 'rating', str(search_data.get('vote_average', '')))
        _add_text(root, 'votes', str(search_data.get('vote_count', '')))

        uid = ET.SubElement(root, 'uniqueid', type='tmdb', default='true')
        uid.text = str(search_data.get('id', ''))

        poster = search_data.get('poster_path')
        if poster:
            thumb = ET.SubElement(root, 'thumb', aspect='poster')
            thumb.text = self._tmdb.get_image_url(poster)

        backdrop = search_data.get('backdrop_path')
        if backdrop:
            fanart = ET.SubElement(root, 'fanart')
            ft = ET.SubElement(fanart, 'thumb')
            ft.text = self._tmdb.get_image_url(backdrop, 'w1280')

        if details:
            for genre in details.get('genres', []):
                _add_text(root, 'genre', genre.get('name', ''))
            credits_data = details.get('credits', {})
            for person in credits_data.get('crew', []):
                if person.get('job') == 'Director':
                    _add_text(root, 'director', person.get('name', ''))
            for actor in credits_data.get('cast', [])[:10]:
                actor_el = ET.SubElement(root, 'actor')
                _add_text(actor_el, 'name', actor.get('name', ''))
                _add_text(actor_el, 'role', actor.get('character', ''))
                if actor.get('profile_path'):
                    _add_text(actor_el, 'thumb', self._tmdb.get_image_url(actor['profile_path']))

        self._write_file(path, _xml_tostring(root))

    def _write_tvshow_nfo(self, path, search_data, details=None):
        root = ET.Element('tvshow')
        _add_text(root, 'title', search_data.get('name', search_data.get('original_name', '')))
        _add_text(root, 'plot', search_data.get('overview', ''))
        _add_text(root, 'rating', str(search_data.get('vote_average', '')))
        first_air = search_data.get('first_air_date', '')
        if first_air:
            _add_text(root, 'year', first_air[:4])

        uid = ET.SubElement(root, 'uniqueid', type='tmdb', default='true')
        uid.text = str(search_data.get('id', ''))

        poster = search_data.get('poster_path')
        if poster:
            thumb = ET.SubElement(root, 'thumb', aspect='poster')
            thumb.text = self._tmdb.get_image_url(poster)

        backdrop = search_data.get('backdrop_path')
        if backdrop:
            fanart = ET.SubElement(root, 'fanart')
            ft = ET.SubElement(fanart, 'thumb')
            ft.text = self._tmdb.get_image_url(backdrop, 'w1280')

        if details:
            for genre in details.get('genres', []):
                _add_text(root, 'genre', genre.get('name', ''))

        self._write_file(path, _xml_tostring(root))

    def _write_episode_nfo(self, path, parsed, search_data, ep_data):
        root = ET.Element('episodedetails')
        _add_text(root, 'season', str(parsed.get('season', 1)))
        _add_text(root, 'episode', str(parsed.get('episode', 1)))

        if ep_data:
            _add_text(root, 'title', ep_data.get('name', ''))
            _add_text(root, 'plot', ep_data.get('overview', ''))
            _add_text(root, 'aired', ep_data.get('air_date', ''))
            _add_text(root, 'rating', str(ep_data.get('vote_average', '')))
            still = ep_data.get('still_path')
            if still:
                thumb = ET.SubElement(root, 'thumb')
                thumb.text = self._tmdb.get_image_url(still)
        else:
            _add_text(root, 'title', parsed.get('title', ''))

        if search_data:
            uid = ET.SubElement(root, 'uniqueid', type='tmdb')
            uid.text = str(search_data.get('id', ''))

        self._write_file(path, _xml_tostring(root))

    def _write_basic_nfo(self, path, media_type, title, year=None):
        tag = media_type if media_type != 'tvshow' else 'tvshow'
        root = ET.Element(tag)
        _add_text(root, 'title', title)
        if year:
            _add_text(root, 'year', str(year))
        self._write_file(path, _xml_tostring(root))

    def _write_file(self, path, content):
        try:
            f = xbmcvfs.File(path, 'w')
            f.write(content)
            f.close()
        except Exception as e:
            debug_trace(f'write failed {path}: {e}')

    def _collect_video_files(self, entries):
        results = []
        for entry in entries:
            if 'e' in entry:
                results.extend(self._collect_video_files(entry['e']))
            elif 'l' in entry and is_video_file(entry.get('n', '')):
                results.append(entry)
        return results

    def _load_manifest(self):
        if not xbmcvfs.exists(self._manifest_path):
            return {}
        try:
            f = xbmcvfs.File(self._manifest_path, 'r')
            data = f.read()
            f.close()
            return json.loads(data) if data else {}
        except Exception:
            return {}

    def _save_manifest(self):
        try:
            f = xbmcvfs.File(self._manifest_path, 'w')
            f.write(json.dumps(self._manifest))
            f.close()
        except Exception:
            pass


def _add_text(parent, tag, text):
    el = ET.SubElement(parent, tag)
    el.text = str(text)
    return el


def _xml_tostring(root):
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')


def _safe_filename(name):
    return ''.join(c if c not in r'<>:"/\|?*' else '_' for c in name).strip('. ')
