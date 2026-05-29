API_BASE = 'https://api.alldebrid.com'
AGENT = 'plugin.video.alldebrid'

MAGNET_STATUS = {
    0: 'In Queue',
    1: 'Downloading',
    2: 'Compressing',
    3: 'Uploading',
    4: 'Ready',
    5: 'Upload Error',
    6: 'Internal Error',
    7: 'Download Too Slow',
    8: 'Duplicate',
    9: 'Dead Torrent',
    10: 'Too Many Active',
    11: 'Size Limit',
    12: 'Timeout',
    13: 'Not Premium',
    14: 'Virus Detected',
    15: 'Server Error',
}

VIDEO_EXTENSIONS = (
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.ts',
    '.m4v', '.mpg', '.mpeg', '.webm', '.ogv', '.3gp', '.m2ts',
)

TMDB_API_BASE = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p'
DEFAULT_TMDB_API_KEY = ''
