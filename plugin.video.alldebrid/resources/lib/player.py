import sys
import json
import traceback
import xbmc
import xbmcgui
import xbmcplugin
from .alldebrid import AllDebridError
from .utils import notify, debug_trace, get_int_setting

HANDLE = int(sys.argv[1])


def _resolve_url(api, link):
    """
    Resolve an AllDebrid link to a final playable URL.
    Returns (play_url, filename) or (None, None) on failure.
    Shows an error dialog on failure.
    """
    try:
        result = api.unlock_link(link)
        debug_trace(f'unlock_link OK. response: {json.dumps(result)[:1200]}')
    except AllDebridError as e:
        debug_trace(f'unlock_link FAILED: [{e.code}] {e.message}')
        xbmcgui.Dialog().ok('AllDebrid Error', f'[{e.code}]\n{e.message}')
        return None, None

    direct_url = result.get('link', '')
    filename = result.get('filename', '')
    streams = result.get('streams') or result.get('streaming') or []
    gen_id = result.get('id', '')

    debug_trace(f'direct_url: {direct_url}')
    debug_trace(f'filename: {filename} | streams: {len(streams)} | gen_id: {gen_id}')

    if not direct_url:
        debug_trace('NO direct_url in response!')
        xbmcgui.Dialog().ok('AllDebrid Error', f'No playable URL.\nKeys: {list(result.keys())}')
        return None, None

    play_url = direct_url
    preferred_quality = get_int_setting('preferred_quality', 0)

    if preferred_quality > 0 and streams and gen_id:
        stream_id = select_stream(streams, preferred_quality)
        debug_trace(f'selected stream_id: {stream_id} for quality {preferred_quality}')
        if stream_id:
            try:
                stream_result = api.get_streaming_link(gen_id, stream_id)
                debug_trace(f'streaming response: {json.dumps(stream_result)[:800]}')
                if stream_result.get('delayed'):
                    delayed_url = wait_for_delayed(api, stream_result['delayed'])
                    if delayed_url:
                        play_url = delayed_url
                else:
                    play_url = stream_result.get('link', direct_url)
            except AllDebridError as e:
                debug_trace(f'streaming failed, using direct: [{e.code}] {e.message}')

    debug_trace(f'FINAL play_url: {play_url}')
    return play_url, filename


def _make_listitem(play_url, filename):
    li = xbmcgui.ListItem(label=filename, path=play_url)
    li.setProperty('IsPlayable', 'true')
    li.setContentLookup(False)
    info = li.getVideoInfoTag()
    info.setTitle(filename)
    return li


def resolve_and_play(api, link):
    """Used when Kodi is in resolve mode (clicking a playable file item)."""
    debug_trace('=== PLAY (resolve mode) ===')
    debug_trace(f'input link: {link}')
    try:
        play_url, filename = _resolve_url(api, link)
        if not play_url:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        li = _make_listitem(play_url, filename)
        debug_trace('calling setResolvedUrl(True)')
        xbmcplugin.setResolvedUrl(HANDLE, True, li)
    except Exception as e:
        debug_trace(f'UNEXPECTED EXCEPTION: {e}')
        debug_trace(traceback.format_exc())
        xbmcgui.Dialog().ok('AllDebrid Error', f'Unexpected error:\n{e}')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def play_direct(api, link):
    """
    Used when NOT in resolve mode (e.g. auto-play after entering a magnet folder).
    Starts playback directly via the Player, which works in any context.
    """
    debug_trace('=== PLAY (direct/Player mode) ===')
    debug_trace(f'input link: {link}')
    try:
        # End the directory first so Kodi isn't left waiting on a folder listing.
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False, updateListing=False, cacheToDisc=False)
        play_url, filename = _resolve_url(api, link)
        if not play_url:
            return
        li = _make_listitem(play_url, filename)
        debug_trace('calling xbmc.Player().play()')
        xbmc.Player().play(play_url, li)
    except Exception as e:
        debug_trace(f'UNEXPECTED EXCEPTION: {e}')
        debug_trace(traceback.format_exc())
        xbmcgui.Dialog().ok('AllDebrid Error', f'Unexpected error:\n{e}')


def select_stream(streams, preferred_quality):
    best_id = None
    best_quality = 0

    for stream in streams:
        quality = stream.get('quality', 0)
        if isinstance(quality, str):
            try:
                quality = int(quality)
            except ValueError:
                continue

        if quality == preferred_quality:
            return stream.get('id', '')

        if quality <= preferred_quality and quality > best_quality:
            best_quality = quality
            best_id = stream.get('id', '')

    return best_id


def wait_for_delayed(api, delayed_id):
    progress = xbmcgui.DialogProgress()
    progress.create('AllDebrid', 'Preparing stream (transcoding)...')

    for i in range(150):
        if progress.iscanceled():
            progress.close()
            return None

        try:
            result = api.check_delayed(delayed_id)
            status = result.get('status', 0)
            time_left = result.get('time_left', 0)

            if status == 2:
                progress.close()
                return result.get('link', '')

            if status == 3:
                progress.close()
                notify('Transcoding failed', icon='error')
                return None

            pct = min(99, int((i / 150) * 100))
            progress.update(pct, f'Transcoding... {time_left}s remaining')

        except AllDebridError as e:
            debug_trace(f'Delayed check error: {e}')

        xbmc.sleep(2000)

    progress.close()
    notify('Transcoding timeout', icon='error')
    return None
