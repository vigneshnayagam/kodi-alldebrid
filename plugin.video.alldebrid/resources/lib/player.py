import sys
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
from .alldebrid import AllDebridAPI, AllDebridError
from .utils import log, notify

HANDLE = int(sys.argv[1])


def resolve_and_play(api, link):
    log(f'resolve_and_play: {link}', level='info')

    # Try to unlock the link through AllDebrid
    try:
        result = api.unlock_link(link)
        log(f'unlock_link result keys: {list(result.keys())}', level='info')
    except AllDebridError as e:
        # If unlock fails, try playing the link directly (already a CDN URL)
        log(f'unlock_link failed ({e.code}: {e.message}), trying direct play', level='error')
        notify(f'AllDebrid: {e.message}', icon='error', time_ms=8000)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    direct_url = result.get('link', '')
    filename = result.get('filename', '')
    streams = result.get('streams', [])
    gen_id = result.get('id', '')

    log(f'direct_url={direct_url} filename={filename} streams={len(streams)} id={gen_id}', level='info')

    if not direct_url:
        notify('AllDebrid returned no playable URL', icon='error', time_ms=8000)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    addon = xbmcaddon.Addon()
    preferred_quality = addon.getSettingInt('preferred_quality')
    play_url = direct_url

    if preferred_quality > 0 and streams and gen_id:
        stream_id = select_stream(streams, preferred_quality)
        if stream_id:
            try:
                stream_result = api.get_streaming_link(gen_id, stream_id)
                if stream_result.get('delayed'):
                    delayed_url = wait_for_delayed(api, stream_result['delayed'])
                    if delayed_url:
                        play_url = delayed_url
                else:
                    play_url = stream_result.get('link', direct_url)
            except AllDebridError as e:
                log(f'Streaming link failed, falling back to direct: {e}', level='error')

    log(f'Playing: {filename} -> {play_url}', level='info')

    li = xbmcgui.ListItem(label=filename, path=play_url, offscreen=True)
    li.setProperty('IsPlayable', 'true')
    xbmcplugin.setResolvedUrl(HANDLE, True, li)


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
