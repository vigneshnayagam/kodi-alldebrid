import os
import time
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
from .constants import MAGNET_STATUS, VIDEO_EXTENSIONS


def _debug_log_path():
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    if not os.path.isdir(profile):
        os.makedirs(profile, exist_ok=True)
    return os.path.join(profile, 'debug.log')


def debug_trace(message):
    """Append a timestamped line to the in-profile debug log (always on)."""
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(_debug_log_path(), 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {message}\n')
    except Exception:
        pass


def read_debug_trace():
    path = _debug_log_path()
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read() or 'Debug log is empty.'
        except Exception as e:
            return f'Could not read debug log: {e}'
    return 'No debug log yet. Try playing a file first.'


def clear_debug_trace():
    path = _debug_log_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def format_size(size_bytes):
    if not size_bytes:
        return ''
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(size_bytes) < 1024.0:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024.0
    return f'{size_bytes:.1f} PB'


def format_status(status_code):
    return MAGNET_STATUS.get(status_code, f'Unknown ({status_code})')


def format_date(timestamp):
    if not timestamp:
        return ''
    return time.strftime('%Y-%m-%d', time.localtime(timestamp))


def is_video_file(filename):
    if not filename:
        return False
    return filename.lower().endswith(VIDEO_EXTENSIONS)


def log(message, level='debug'):
    addon = xbmcaddon.Addon()
    debug_enabled = addon.getSettingBool('debug_logging')
    prefix = '[AllDebrid Cloud]'
    if level == 'error':
        xbmc.log(f'{prefix} {message}', xbmc.LOGERROR)
    elif level == 'info':
        xbmc.log(f'{prefix} {message}', xbmc.LOGINFO)
    elif debug_enabled:
        xbmc.log(f'{prefix} {message}', xbmc.LOGDEBUG)


def notify(message, icon='info', time_ms=5000):
    icons = {
        'info': xbmcgui.NOTIFICATION_INFO,
        'warning': xbmcgui.NOTIFICATION_WARNING,
        'error': xbmcgui.NOTIFICATION_ERROR,
    }
    xbmcgui.Dialog().notification(
        'AllDebrid Cloud',
        message,
        icons.get(icon, xbmcgui.NOTIFICATION_INFO),
        time_ms,
    )
