import sys
from urllib.parse import parse_qs, urlencode, quote_plus, unquote_plus

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

from resources.lib.alldebrid import AllDebridAPI, AllDebridError
from resources.lib.auth import ensure_auth, clear_auth
from resources.lib.player import resolve_and_play
from resources.lib.utils import (
    format_size, format_status, format_date, is_video_file, log, notify,
    read_debug_trace, clear_debug_trace, get_bool_setting,
)

ADDON = xbmcaddon.Addon()
PLUGIN_URL = sys.argv[0]
HANDLE = int(sys.argv[1])


def get_params():
    params = {}
    qs = sys.argv[2]
    if qs:
        for key, values in parse_qs(qs.lstrip('?')).items():
            params[key] = values[0]
    return params


def build_url(**kwargs):
    return f'{PLUGIN_URL}?{urlencode(kwargs)}'


def get_api():
    api_key = ADDON.getSetting('api_key')
    if not api_key:
        api_key = ensure_auth()
        if not api_key:
            return None
    return AllDebridAPI(api_key)


def handle_api_error(error):
    if error.code in ('AUTH_MISSING_APIKEY', 'AUTH_BAD_APIKEY', 'AUTH_BLOCKED'):
        notify('Authentication failed. Please re-authenticate.', icon='error')
        ADDON.setSetting('api_key', '')
    elif error.code == 'MUST_BE_PREMIUM':
        notify('AllDebrid Premium account required.', icon='error')
    else:
        notify(f'Error: {error.message}', icon='error')
    log(f'API error: {error}', level='error')


# --- Menu Builders ---


def main_menu():
    items = [
        (build_url(action='magnets'),
         _folder_item('My Magnets', 'DefaultFolder.png'), True),
        (build_url(action='saved_links'),
         _folder_item('Saved Links', 'DefaultFolder.png'), True),
        (build_url(action='add_magnet'),
         _folder_item('Add Magnet', 'DefaultAddSource.png'), False),
        (build_url(action='reauth'),
         _folder_item('Re-authenticate', 'DefaultUser.png'), False),
        (build_url(action='debug_log'),
         _folder_item('Debug Log', 'DefaultAddonService.png'), False),
        (build_url(action='settings'),
         _folder_item('Settings', 'DefaultAddonProgram.png'), False),
    ]
    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.endOfDirectory(HANDLE)


def list_magnets():
    api = get_api()
    if not api:
        return

    try:
        magnets = api.get_magnets()
    except AllDebridError as e:
        handle_api_error(e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    if not magnets:
        notify('No magnets found. Add one from the main menu.')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    items = []
    for m in magnets:
        status_code = m.get('statusCode', 0)
        status_text = format_status(status_code)
        size_text = format_size(m.get('size', 0))
        name = m.get('filename', 'Unknown')
        magnet_id = m.get('id')

        label = f'{name}  [{status_text}]'
        if size_text:
            label += f'  ({size_text})'

        li = xbmcgui.ListItem(label=label)

        if status_code == 4:
            li.setArt({'icon': 'DefaultFolder.png'})
        elif status_code == 1:
            li.setArt({'icon': 'DefaultNetwork.png'})
        else:
            li.setArt({'icon': 'DefaultFile.png'})

        context_items = [
            ('Delete Magnet',
             f'RunPlugin({build_url(action="delete_magnet", id=magnet_id)})'),
        ]
        if status_code >= 5:
            context_items.append(
                ('Restart Magnet',
                 f'RunPlugin({build_url(action="restart_magnet", id=magnet_id)})'),
            )
        li.addContextMenuItems(context_items)

        if status_code == 4:
            url = build_url(action='magnet_files', id=magnet_id)
            items.append((url, li, True))
        else:
            items.append(('', li, False))

    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE)


def list_magnet_files(magnet_id):
    api = get_api()
    if not api:
        return

    try:
        files = api.get_magnet_files(magnet_id)
    except AllDebridError as e:
        handle_api_error(e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    if not files:
        notify('No files found in this magnet.')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    video_files = _collect_video_files(files)
    auto_play = get_bool_setting('auto_play_single', True)

    if auto_play and len(video_files) == 1:
        link = video_files[0].get('l', '')
        if link:
            resolve_and_play(api, link)
            return

    _build_file_listing(files, magnet_id)


def list_folder(magnet_id, path):
    api = get_api()
    if not api:
        return

    try:
        files = api.get_magnet_files(magnet_id)
    except AllDebridError as e:
        handle_api_error(e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    decoded_path = unquote_plus(path)
    segments = decoded_path.split('/')
    current = files

    for segment in segments:
        found = False
        for entry in current:
            if entry.get('n') == segment and 'e' in entry:
                current = entry['e']
                found = True
                break
        if not found:
            notify('Folder not found', icon='error')
            xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
            return

    _build_file_listing(current, magnet_id, decoded_path)


def list_saved_links():
    api = get_api()
    if not api:
        return

    try:
        links = api.get_user_links()
    except AllDebridError as e:
        handle_api_error(e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    if not links:
        notify('No saved links found.')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    items = []
    for link_data in links:
        filename = link_data.get('filename', link_data.get('link', 'Unknown'))
        size = format_size(link_data.get('size', 0))
        date = format_date(link_data.get('date', 0))

        label = filename
        if size:
            label += f'  ({size})'
        if date:
            label += f'  [{date}]'

        li = xbmcgui.ListItem(label=label)
        li.setProperty('IsPlayable', 'true')

        if is_video_file(filename):
            li.setArt({'icon': 'DefaultVideo.png'})
            info_tag = li.getVideoInfoTag()
            info_tag.setTitle(filename)

        link = link_data.get('link', '')
        url = build_url(action='play', link=quote_plus(link))
        items.append((url, li, False))

    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.setContent(HANDLE, 'videos')
    xbmcplugin.endOfDirectory(HANDLE)


# --- Actions ---


def play_link(link):
    api = get_api()
    if not api:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    decoded_link = unquote_plus(link)
    resolve_and_play(api, decoded_link)


def delete_magnet(magnet_id):
    if not xbmcgui.Dialog().yesno('Delete Magnet', 'Are you sure you want to delete this magnet?'):
        return
    api = get_api()
    if not api:
        return
    try:
        api.delete_magnet(magnet_id)
        notify('Magnet deleted')
        xbmc.executebuiltin('Container.Refresh')
    except AllDebridError as e:
        handle_api_error(e)


def restart_magnet(magnet_id):
    api = get_api()
    if not api:
        return
    try:
        api.restart_magnet(magnet_id)
        notify('Magnet restarted')
        xbmc.executebuiltin('Container.Refresh')
    except AllDebridError as e:
        handle_api_error(e)


def show_debug_log():
    content = read_debug_trace()
    choice = xbmcgui.Dialog().textviewer('AllDebrid Debug Log', content)
    if xbmcgui.Dialog().yesno('Debug Log', 'Clear the debug log?'):
        clear_debug_trace()


def add_magnet_dialog():
    magnet_uri = xbmcgui.Dialog().input('Enter Magnet Link or Hash')
    if not magnet_uri:
        return
    api = get_api()
    if not api:
        return
    try:
        result = api.upload_magnet(magnet_uri)
        magnets = result.get('magnets', [])
        if magnets:
            name = magnets[0].get('name', 'Unknown')
            notify(f'Magnet added: {name}')
        else:
            notify('Magnet added')
    except AllDebridError as e:
        handle_api_error(e)


# --- Helpers ---


def _folder_item(label, icon):
    li = xbmcgui.ListItem(label=label)
    li.setArt({'icon': icon})
    return li


def _build_file_listing(entries, magnet_id, path_prefix=''):
    items = []
    for entry in entries:
        name = entry.get('n', 'Unknown')

        if 'e' in entry:
            li = xbmcgui.ListItem(label=name)
            li.setArt({'icon': 'DefaultFolder.png'})
            sub_path = f'{path_prefix}/{name}' if path_prefix else name
            url = build_url(action='folder', id=magnet_id, path=quote_plus(sub_path))
            items.append((url, li, True))

        elif 'l' in entry:
            size_text = format_size(entry.get('s', 0))
            label = name
            if size_text:
                label += f'  ({size_text})'

            li = xbmcgui.ListItem(label=label)
            li.setProperty('IsPlayable', 'true')

            if is_video_file(name):
                li.setArt({'icon': 'DefaultVideo.png'})
                info_tag = li.getVideoInfoTag()
                info_tag.setTitle(name)
            else:
                li.setArt({'icon': 'DefaultFile.png'})

            url = build_url(action='play', link=quote_plus(entry['l']))
            items.append((url, li, False))

    xbmcplugin.addDirectoryItems(HANDLE, items, len(items))
    xbmcplugin.setContent(HANDLE, 'videos')
    xbmcplugin.endOfDirectory(HANDLE)


def _collect_video_files(entries):
    results = []
    for entry in entries:
        if 'e' in entry:
            results.extend(_collect_video_files(entry['e']))
        elif 'l' in entry and is_video_file(entry.get('n', '')):
            results.append(entry)
    return results


# --- Router ---


def router():
    params = get_params()
    action = params.get('action')

    if action is None:
        main_menu()
    elif action == 'magnets':
        list_magnets()
    elif action == 'magnet_files':
        list_magnet_files(int(params['id']))
    elif action == 'folder':
        list_folder(int(params['id']), params['path'])
    elif action == 'saved_links':
        list_saved_links()
    elif action == 'play':
        play_link(params['link'])
    elif action == 'delete_magnet':
        delete_magnet(int(params['id']))
    elif action == 'restart_magnet':
        restart_magnet(int(params['id']))
    elif action == 'add_magnet':
        add_magnet_dialog()
    elif action == 'reauth':
        clear_auth()
        ensure_auth()
    elif action == 'debug_log':
        show_debug_log()
    elif action == 'settings':
        ADDON.openSettings()


if __name__ == '__main__':
    router()
