import sys
import json
import traceback
import xbmc
import xbmcgui
import xbmcplugin
from .alldebrid import AllDebridError
from .utils import notify, debug_trace, get_int_setting, get_bool_setting
from .resume import get_resume_position, save_resume_position, clear_resume_position

HANDLE = int(sys.argv[1])

_active_player = None


class AllDebridPlayer(xbmc.Player):

    def __init__(self, link, filename, resume=None):
        super().__init__()
        self._link = link
        self._filename = filename
        self._resume = resume  # dict from get_resume_position, or None
        self._tracking = True

    def onAVStarted(self):
        """Fires once audio/video streams are actually loaded — safe to set tracks here."""
        if not self._resume:
            return
        try:
            self._restore_audio()
            self._restore_subtitles()
        except RuntimeError:
            pass

    def onPlayBackStopped(self):
        self._save_position()
        self._tracking = False

    def onPlayBackPaused(self):
        self._save_position()

    def onPlayBackEnded(self):
        clear_resume_position(self._link)
        self._tracking = False

    def _restore_audio(self):
        saved_idx = self._resume.get('audio_idx')
        saved_name = self._resume.get('audio_name', '')
        if saved_idx is None and not saved_name:
            return

        streams = self.getAvailableAudioStreams()
        if not streams:
            return

        # Prefer name match (robust across re-encodes / fresh URLs)
        if saved_name:
            for i, name in enumerate(streams):
                if saved_name.lower() in str(name).lower():
                    debug_trace(f'restore audio: name match "{name}" at index {i}')
                    self.setAudioStream(i)
                    return

        # Fall back to stored index
        if saved_idx is not None and 0 <= saved_idx < len(streams):
            debug_trace(f'restore audio: index fallback {saved_idx}')
            self.setAudioStream(saved_idx)

    def _restore_subtitles(self):
        saved_idx = self._resume.get('sub_idx')
        saved_name = self._resume.get('sub_name', '')
        subs_showing = self._resume.get('subs_showing', False)

        if saved_idx is not None or saved_name:
            streams = self.getAvailableSubtitleStreams()
            if streams:
                matched = False
                if saved_name:
                    for i, name in enumerate(streams):
                        if saved_name.lower() in str(name).lower():
                            debug_trace(f'restore subtitle: name match "{name}" at index {i}')
                            self.setSubtitles(i)
                            matched = True
                            break
                if not matched and saved_idx is not None and 0 <= saved_idx < len(streams):
                    debug_trace(f'restore subtitle: index fallback {saved_idx}')
                    self.setSubtitles(saved_idx)

        self.showSubtitles(subs_showing)
        debug_trace(f'restore subtitles: showing={subs_showing}')

    def _save_position(self):
        if not self._tracking:
            return
        try:
            pos = self.getTime()
            total = self.getTotalTime()
            if total > 0 and pos > 0:
                if pos / total > 0.90:
                    clear_resume_position(self._link)
                    return

                audio_idx = None
                audio_name = ''
                sub_idx = None
                sub_name = ''
                subs_showing = False

                try:
                    audio_idx = self.getAudioStream()
                    audio_streams = self.getAvailableAudioStreams()
                    if audio_streams and 0 <= audio_idx < len(audio_streams):
                        audio_name = str(audio_streams[audio_idx])
                except Exception:
                    pass

                try:
                    sub_idx = self.getSubtitleStream()
                    sub_streams = self.getAvailableSubtitleStreams()
                    if sub_streams and 0 <= sub_idx < len(sub_streams):
                        sub_name = str(sub_streams[sub_idx])
                    subs_showing = self.isSubtitlesShowing()
                except Exception:
                    pass

                debug_trace(
                    f'save resume: pos={pos:.1f} audio={audio_idx}("{audio_name}") '
                    f'sub={sub_idx}("{sub_name}") subs_showing={subs_showing}'
                )
                save_resume_position(
                    self._link, pos, total, self._filename,
                    audio_idx, audio_name, sub_idx, sub_name, subs_showing,
                )
        except RuntimeError:
            pass


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


def _make_listitem(play_url, filename, resume_position=0, resume_total=0):
    li = xbmcgui.ListItem(label=filename, path=play_url)
    li.setProperty('IsPlayable', 'true')
    li.setContentLookup(False)
    info = li.getVideoInfoTag()
    info.setTitle(filename)
    if resume_position > 0 and resume_total > 0:
        li.setProperty('ResumeTime', str(resume_position))
        li.setProperty('TotalTime', str(resume_total))
    return li


def resolve_and_play(api, link):
    """Used when Kodi is in resolve mode (clicking a playable file item)."""
    global _active_player
    debug_trace('=== PLAY (resolve mode) ===')
    debug_trace(f'input link: {link}')
    try:
        play_url, filename = _resolve_url(api, link)
        if not play_url:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return

        resume = None
        if get_bool_setting('enable_resume', True):
            resume = get_resume_position(link)
            debug_trace(f'resume: pos={resume["position"]:.1f} audio={resume["audio_idx"]} sub={resume["sub_idx"]}')

        position = resume['position'] if resume else 0.0
        total = resume['total'] if resume else 0.0
        li = _make_listitem(play_url, filename, position, total)
        debug_trace('calling setResolvedUrl(True)')
        xbmcplugin.setResolvedUrl(HANDLE, True, li)
        _active_player = AllDebridPlayer(link, filename, resume)
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
    global _active_player
    debug_trace('=== PLAY (direct/Player mode) ===')
    debug_trace(f'input link: {link}')
    try:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False, updateListing=False, cacheToDisc=False)
        play_url, filename = _resolve_url(api, link)
        if not play_url:
            return

        resume = None
        if get_bool_setting('enable_resume', True):
            resume = get_resume_position(link)
            debug_trace(f'resume: pos={resume["position"]:.1f} audio={resume["audio_idx"]} sub={resume["sub_idx"]}')

        position = resume['position'] if resume else 0.0
        total = resume['total'] if resume else 0.0
        li = _make_listitem(play_url, filename, position, total)
        debug_trace('calling AllDebridPlayer.play()')
        _active_player = AllDebridPlayer(link, filename, resume)
        _active_player.play(play_url, li)
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
