#!/usr/bin/env python3
"""
Generates the Kodi repository artifacts:
  - Zips each addon under repo/<addon-id>/<addon-id>-<version>.zip
  - Generates repo/addons.xml + addons.xml.md5
  - Generates Apache-style index.html in each repo subdirectory
    so Kodi can browse the GitHub Pages site as a directory listing

Run from the kodi_agent/ directory:
    python3 generate_repo.py
"""

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


def zip_addon(addon_dir, addon_id, version):
    zip_dir = os.path.join(REPO_DIR, addon_id)
    os.makedirs(zip_dir, exist_ok=True)
    zip_path = os.path.join(zip_dir, f'{addon_id}-{version}.zip')

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


def main():
    print('Generating Kodi repository...\n')

    addon_roots = []
    for addon_dir in ADDON_SOURCES:
        if not os.path.isdir(addon_dir):
            print(f'WARNING: skipping missing dir: {addon_dir}')
            continue
        addon_id, version, root = get_addon_info(addon_dir)
        print(f'Processing {addon_id} v{version}')
        zip_addon(addon_dir, addon_id, version)
        addon_roots.append(root)

    print()

    # addons.xml + md5
    addons_xml = generate_addons_xml(addon_roots)
    with open(os.path.join(REPO_DIR, 'addons.xml'), 'w', encoding='utf-8') as f:
        f.write(addons_xml)
    md5 = hashlib.md5(addons_xml.encode('utf-8')).hexdigest()
    with open(os.path.join(REPO_DIR, 'addons.xml.md5'), 'w', encoding='utf-8') as f:
        f.write(md5)
    print(f'Generated addons.xml (md5: {md5})')

    # index.html files for Kodi directory browsing
    print('\nGenerating index.html files...')
    write_index(REPO_DIR, 'repo')
    for name in os.listdir(REPO_DIR):
        subdir = os.path.join(REPO_DIR, name)
        if os.path.isdir(subdir):
            write_index(subdir, f'repo/{name}')

    print(f'''
Done! Push to GitHub and enable GitHub Pages:

  git add repo/ && git commit -m "Update repo" && git push
  gh api repos/vigneshnayagam/kodi-alldebrid/pages \\
    --method POST -f source[branch]=main -f source[path]=/

Then in Kodi:
  Settings → File Manager → Add source
  URL: {PAGES_BASE}/repo/
  Name: AllDebrid Repo

  Add-ons → Install from zip file → AllDebrid Repo
    → repository.alldebrid/ → repository.alldebrid-1.0.0.zip
''')


if __name__ == '__main__':
    main()
