import time
import xbmc
import xbmcgui
import xbmcaddon
from .alldebrid import AllDebridAPI, AllDebridError
from .utils import log, notify


def ensure_auth():
    addon = xbmcaddon.Addon()
    api_key = addon.getSetting('api_key')

    if api_key:
        if validate_api_key(api_key):
            return api_key
        addon.setSetting('api_key', '')
        notify('API key expired or invalid. Please re-authenticate.', icon='warning')

    return do_pin_auth()


def do_pin_auth():
    api = AllDebridAPI()
    try:
        pin_data = api.pin_get()
    except AllDebridError as e:
        notify(f'Failed to start authentication: {e.message}', icon='error')
        log(f'PIN get failed: {e}', level='error')
        return ''

    pin = pin_data.get('pin', '')
    user_url = pin_data.get('user_url', 'https://alldebrid.com/pin/')
    check_token = pin_data.get('check', '')
    expires_in = pin_data.get('expires_in', 600)

    progress = xbmcgui.DialogProgress()
    progress.create(
        'AllDebrid Authentication',
        f'Visit: [B]{user_url}[/B]\n\nEnter PIN: [B]{pin}[/B]\n\nWaiting for authorization...',
    )

    start_time = time.time()
    poll_interval = 5

    while not progress.iscanceled():
        elapsed = time.time() - start_time
        remaining = expires_in - elapsed

        if remaining <= 0:
            progress.close()
            notify('PIN expired. Please try again.', icon='warning')
            return ''

        pct = int((elapsed / expires_in) * 100)
        progress.update(pct)

        try:
            check_data = api.pin_check(check_token, pin)
            if check_data.get('activated'):
                api_key = check_data.get('apikey', '')
                if api_key:
                    progress.close()
                    _store_api_key(api_key)
                    notify('Authentication successful!')
                    return api_key
        except AllDebridError:
            pass

        for _ in range(poll_interval * 2):
            if progress.iscanceled():
                break
            xbmc.sleep(500)

    progress.close()
    return ''


def validate_api_key(api_key):
    api = AllDebridAPI(api_key)
    try:
        user_data = api.get_user()
        _update_user_info(user_data)
        return True
    except AllDebridError as e:
        log(f'API key validation failed: {e}', level='error')
        return False


def clear_auth():
    addon = xbmcaddon.Addon()
    addon.setSetting('api_key', '')
    addon.setSetting('username', '')
    addon.setSetting('premium_until', '')


def _store_api_key(api_key):
    addon = xbmcaddon.Addon()
    addon.setSetting('api_key', api_key)

    api = AllDebridAPI(api_key)
    try:
        user_data = api.get_user()
        _update_user_info(user_data)
    except AllDebridError as e:
        log(f'Failed to fetch user info after auth: {e}', level='error')


def _update_user_info(user_data):
    addon = xbmcaddon.Addon()
    user = user_data.get('user', user_data)
    addon.setSetting('username', user.get('username', ''))

    premium_until = user.get('premiumUntil')
    if premium_until:
        import datetime
        try:
            dt = datetime.datetime.fromtimestamp(premium_until)
            addon.setSetting('premium_until', dt.strftime('%Y-%m-%d'))
        except (ValueError, OSError):
            addon.setSetting('premium_until', str(premium_until))
