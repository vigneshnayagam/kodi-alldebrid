#!/usr/bin/env python3
"""
Generates the Kodi repository artifacts.

Stable build (updates addons.xml, used by Kodi auto-updates):
    python3 generate_repo.py

Dev build (drops zip into repo/plugin.video.alldebrid/dev/, no addons.xml change):
    python3 generate_repo.py --dev
"""

import argparse
import hashlib
import os
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_SOURCES = [
    os.path.join(SCRIPT_DIR, 'plugin.video.alldebrid'),
    os.path.join(SCRIPT_DIR, 'repo', 'repository.alldebrid'),
]
REPO_DIR = os.path.join(SCRIPT_DIR, 'repo')

PAGES_BASE = 'https://vigneshnayagam.github.io/kodi-alldebrid'


def get_addon_info(addon_dir):
    xml_path = os.path.join(addon_dir, 'addon.xml')
    tree = ET.parse(xml_path)
    root = tree.getroot()
    return root.get('id'), root.get('version'), root


def zip_addon(addon_dir, addon_id, version, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, f'{addon_id}-{version}.zip')

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(addon_dir):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for filename in filenames:
                if filename.endswith('.pyc'):
                    continue
                filepath = os.path.join(dirpath, filename)
                arcname = os.path.join(addon_id, os.path.relpath(filepath, addon_dir))
                zf.write(filepath, arcname)

    print(f'  Zipped: {zip_path}')
    return zip_path


def generate_addons_xml(addon_roots):
    addons_root = ET.Element('addons')
    for root in addon_roots:
        addons_root.append(root)
    xml_str = ET.tostring(addons_root, encoding='unicode')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str


def generate_index_html(directory, title):
    """
    Produce an Apache-style directory listing HTML that Kodi's HTTP VFS
    can parse (it scans for <a href="..."> links).
    """
    entries = []
    for name in sorted(os.listdir(directory)):
        if name.startswith('.') or name == 'index.html':
            continue
        full = os.path.join(directory, name)
        is_dir = os.path.isdir(full)
        size = '-' if is_dir else str(os.path.getsize(full))
        suffix = '/' if is_dir else ''
        entries.append((name + suffix, size))

    rows = '\n'.join(
        f'<tr><td><a href="{name}">{name}</a></td><td>{size}</td></tr>'
        for name, size in entries
    )

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    return f'''<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
 <head><title>Index of /{title}</title></head>
 <body>
  <h1>Index of /{title}</h1>
  <table>
   <tr><th>Name</th><th>Size</th></tr>
   <tr><th colspan="2"><hr></th></tr>
   <tr><td><a href="../">Parent Directory</a></td><td>-</td></tr>
{rows}
   <tr><th colspan="2"><hr></th></tr>
  </table>
  <address>Generated {now}</address>
 </body>
</html>'''


def write_index(directory, title):
    html = generate_index_html(directory, title)
    path = os.path.join(directory, 'index.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'  index.html: {path}')


def refresh_indexes():
    write_index(REPO_DIR, 'repo')
    for name in os.listdir(REPO_DIR):
        subdir = os.path.join(REPO_DIR, name)
        if os.path.isdir(subdir):
            write_index(subdir, f'repo/{name}')
            dev_dir = os.path.join(subdir, 'dev')
            if os.path.isdir(dev_dir):
                write_index(dev_dir, f'repo/{name}/dev')


def build_stable():
    print('Generating stable Kodi repository...\n')

    addon_roots = []
    for addon_dir in ADDON_SOURCES:
        if not os.path.isdir(addon_dir):
            print(f'WARNING: skipping missing dir: {addon_dir}')
            continue
        addon_id, version, root = get_addon_info(addon_dir)
        out_dir = os.path.join(REPO_DIR, addon_id)
        print(f'Processing {addon_id} v{version}')
        zip_addon(addon_dir, addon_id, version, out_dir)
        addon_roots.append(root)

    print()

    addons_xml = generate_addons_xml(addon_roots)
    with open(os.path.join(REPO_DIR, 'addons.xml'), 'w', encoding='utf-8') as f:
        f.write(addons_xml)
    md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    with open(os.path.join(REPO_DIR, 'addons.xml.md5'), 'w', encoding='utf-8') as f:
        f.write(md5)
    print(f'Generated addons.xml (md5: {md5})')

    print('\nGenerating index.html files...')
    refresh_indexes()

    print(f'''
Done! Commit and push:

  git add repo/ && git commit -m "v{addon_roots[0].get("version") if addon_roots else "?"}: stable release" && git push

Kodi repo URL: {PAGES_BASE}/repo/
''')


def build_dev():
    print('Generating dev build...\n')

    addon_dir = os.path.join(SCRIPT_DIR, 'plugin.video.alldebrid')
    if not os.path.isdir(addon_dir):
        print(f'ERROR: {addon_dir} not found')
        return

    addon_id, version, _ = get_addon_info(addon_dir)
    out_dir = os.path.join(REPO_DIR, addon_id, 'dev')
    print(f'Processing {addon_id} v{version} → dev/')
    zip_addon(addon_dir, addon_id, version, out_dir)

    print('\nGenerating index.html files...')
    refresh_indexes()

    dev_url = f'{PAGES_BASE}/repo/{addon_id}/dev/'
    print(f'''
Done! Commit and push:

  git add repo/{addon_id}/dev/ repo/{addon_id}/index.html repo/index.html
  git commit -m "Dev build: {addon_id} v{version}"
  git push

To install in Kodi:
  Add-ons → Install from zip file → AllDebrid Repo
    → {addon_id}/ → dev/ → {addon_id}-{version}.zip

Or browse directly: {dev_url}
''')


def main():
    parser = argparse.ArgumentParser(description='Generate Kodi repository artifacts')
    parser.add_argument('--dev', action='store_true',
                        help='Build dev zip into repo/<addon>/dev/ without touching addons.xml')
    args = parser.parse_args()

    if args.dev:
        build_dev()
    else:
        build_stable()


if __name__ == '__main__':
    main()
