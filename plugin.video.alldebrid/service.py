"""
Background service — runs for the lifetime of Kodi while the addon is enabled.
Owns the xbmc.Player subclass so callbacks survive past the plugin process exit.
Communicates with the plugin via current_play.json in the addon profile.
"""
import json
import xbmc
import xbmcaddon
import xbmcvfs

from resources.lib.resume import (
    get_resume_position, save_resume_position, clear_resume_position,
)
from resources.lib.utils import debug_trace


def _profile():
    addon = xbmcaddon.Addon()
    path = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    xbmcvfs.mkdirs(path)
    return path


def _current_play_path():
    return _profile() + 'current_play.json'


def _read_current():
    path = _current_play_path()
    if not xbmcvfs.exists(path):
        return None
    try:
        f = xbmcvfs.File(path, 'r')
        data = f.read()
        f.close()
        return json.loads(data) if data else None
    except Exception:
        return None


def _clear_current():
    path = _current_play_path()
    if xbmcvfs.exists(path):
        xbmcvfs.delete(path)


class AllDebridPlayerService(xbmc.Player):

    def __init__(self):
        super().__init__()
        self._current = None  # dict: {link, filename} written by plugin before play()

    def onAVStarted(self):
        """Streams are loaded and ready — safe to restore audio/subtitle selections."""
        self._current = _read_current()
        if not self._current:
            return

        link = self._current.get('link', '')
        resume = get_resume_position(link)
        debug_trace(
            f'[service] onAVStarted: link={link[:40]}... '
            f'pos={resume["position"]:.1f} audio={resume["audio_idx"]} sub={resume["sub_idx"]}'
        )

        if resume['position'] <= 0 and resume['audio_idx'] is None and resume['sub_idx'] is None:
            return  # Nothing saved for this item

        try:
            self._restore_audio(resume)
            self._restore_subtitles(resume)
        except RuntimeError:
            pass

    def onPlayBackStopped(self):
        debug_trace('[service] onPlayBackStopped')
        self._save_state()
        self._current = None

    def onPlayBackPaused(self):
        debug_trace('[service] onPlayBackPaused')
        self._save_state()

    def onPlayBackResumed(self):
        debug_trace('[service] onPlayBackResumed')

    def onPlayBackEnded(self):
        debug_trace('[service] onPlayBackEnded')
        if self._current:
            clear_resume_position(self._current['link'])
        _clear_current()
        self._current = None

    def _restore_audio(self, resume):
        saved_idx = resume.get('audio_idx')
        saved_name = resume.get('audio_name', '')
        if saved_idx is None and not saved_name:
            return

        streams = self.getAvailableAudioStreams()
        if not streams:
            return

        if saved_name:
            for i, name in enumerate(streams):
                if saved_name.lower() in str(name).lower():
                    debug_trace(f'[service] restore audio by name: "{name}" -> {i}')
                    self.setAudioStream(i)
                    return

        if saved_idx is not None and 0 <= saved_idx < len(streams):
            debug_trace(f'[service] restore audio by index: {saved_idx}')
            self.setAudioStream(saved_idx)

    def _restore_subtitles(self, resume):
        saved_idx = resume.get('sub_idx')
        saved_name = resume.get('sub_name', '')
        subs_showing = resume.get('subs_showing', False)

        if saved_idx is not None or saved_name:
            streams = self.getAvailableSubtitleStreams()
            if streams:
                matched = False
                if saved_name:
                    for i, name in enumerate(streams):
                        if saved_name.lower() in str(name).lower():
                            debug_trace(f'[service] restore subtitle by name: "{name}" -> {i}')
                            self.setSubtitles(i)
                            matched = True
                            break
                if not matched and saved_idx is not None and 0 <= saved_idx < len(streams):
                    debug_trace(f'[service] restore subtitle by index: {saved_idx}')
                    self.setSubtitles(saved_idx)

        self.showSubtitles(subs_showing)
        debug_trace(f'[service] subtitles showing: {subs_showing}')

    def _save_state(self):
        if not self._current:
            return
        link = self._current['link']
        filename = self._current.get('filename', '')
        try:
            pos = self.getTime()
            total = self.getTotalTime()
            if not (total > 0 and pos > 0):
                return

            if pos / total > 0.90:
                debug_trace(f'[service] watched >90%, clearing resume')
                clear_resume_position(link)
                _clear_current()
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
                f'[service] saving: pos={pos:.1f}/{total:.1f} '
                f'audio={audio_idx}("{audio_name}") '
                f'sub={sub_idx}("{sub_name}") subs={subs_showing}'
            )
            save_resume_position(
                link, pos, total, filename,
                audio_idx, audio_name, sub_idx, sub_name, subs_showing,
            )
        except RuntimeError:
            pass


if __name__ == '__main__':
    player = AllDebridPlayerService()
    monitor = xbmc.Monitor()
    debug_trace('[service] started')
    while not monitor.abortRequested():
        monitor.waitForAbort(1)
    debug_trace('[service] stopped')
