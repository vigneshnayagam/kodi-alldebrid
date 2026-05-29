import hashlib
import json
import time
import xbmcaddon
import xbmcvfs


def _db_path():
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    xbmcvfs.mkdirs(profile)
    return profile + 'resume.json'


def _load_db():
    path = _db_path()
    if not xbmcvfs.exists(path):
        return {}
    try:
        f = xbmcvfs.File(path, 'r')
        data = f.read()
        f.close()
        return json.loads(data) if data else {}
    except Exception:
        return {}


def _save_db(db):
    try:
        f = xbmcvfs.File(_db_path(), 'w')
        f.write(json.dumps(db))
        f.close()
    except Exception:
        pass


def _key(link):
    return hashlib.md5(link.encode('utf-8')).hexdigest()


def get_resume_position(link):
    db = _load_db()
    entry = db.get(_key(link))
    if not entry:
        return 0.0, 0.0
    return float(entry.get('position', 0)), float(entry.get('total', 0))


def save_resume_position(link, position, total, filename=''):
    db = _load_db()
    db[_key(link)] = {
        'position': position,
        'total': total,
        'filename': filename,
        'updated': int(time.time()),
    }
    cutoff = int(time.time()) - 90 * 86400
    db = {k: v for k, v in db.items() if v.get('updated', 0) > cutoff}
    _save_db(db)


def clear_resume_position(link):
    db = _load_db()
    db.pop(_key(link), None)
    _save_db(db)
