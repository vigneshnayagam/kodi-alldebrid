import sys
import json
import traceback
import xbmc
import xbmcgui
import xbmcplugin
from .alldebrid import AllDebridAPI, AllDebridError
from .utils import log, notify, debug_trace, get_int_setting

HANDLE = int(sys.argv[1])


def resolve_and_play(api, link):
    debug_trace('=== PLAY ATTEMPT ===')
    debug_trace(f'input link: {link}')

    try:
        _resolve_and_play_inner(api, link)
    except Exception as e:
        debug_trace(f'UNEXPECTED EXCEPTION: {e}')
        debug_trace(traceback.format_exc())
        xbmcgui.Dialog().ok('AllDebrid Error', f'Unexpected error:\n{e}')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def _resolve_and_play_inner(api, link):
    try:
        result = api.unlock_link(link)
        debug_trace(f'unlock_link OK. full response: {json.dumps(result)[:1500]}')
    except AllDebridError as e:
        debug_trace(f'unlock_link FAILED: [{e.code}] {e.message}')
        xbmcgui.Dialog().ok('AllDebrid Error', f'[{e.code}]\n{e.message}')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    direct_url = result.get('link', '')
    filename = result.get('filename', '')
    streams = result.get('streams') or result.get('streaming') or []
    gen_id = result.get('id', '')

    debug_trace(f'direct_url: {direct_url}')
    debug_trace(f'filename: {filename}')
    debug_trace(f'streams count: {len(streams)}, gen_id: {gen_id}')

    if not direct_url:
        debug_trace('NO direct_url in response!')
        xbmcgui.Dialog().ok('AllDebrid Error', f'No playable URL.\nKeys: {list(result.keys())}')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    preferred_quality = get_int_setting('preferred_quality', 0)
    play_url = direct_url

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
    debug_trace(f'play_url scheme: {play_url.split("://")[0] if "://" in play_url else "NONE"}')

    li = xbmcgui.ListItem(label=filename, path=play_url, offscreen=True)
    li.setProperty('IsPlayable', 'true')
    li.setMimeType('video/mp4')
    li.setContentLookup(False)
    debug_trace('calling setResolvedUrl(True)')
    xbmcplugin.setResolvedUrl(HANDLE, True, li)
    debug_trace('setResolvedUrl returned')


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
            log(f'Delayed check error: {e}', level='error')

        xbmc.sleep(2000)

    progress.close()
    notify('Transcoding timeout', icon='error')
    return None
