#!/usr/bin/env python3
"""
Generates the Kodi repository artifacts:
  - Zips each addon under repo/<addon-id>/<addon-id>-<version>.zip
  - Generates repo/addons.xml from each addon's addon.xml
  - Generates repo/addons.xml.md5

Run from the kodi_agent/ directory:
    python3 generate_repo.py
"""

import hashlib
import os
import re
import shutil
import sys
import zipfile
from xml.etree import ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_SOURCES = [
    os.path.join(SCRIPT_DIR, 'plugin.video.alldebrid'),
    os.path.join(SCRIPT_DIR, 'repo', 'repository.alldebrid'),
]
REPO_DIR = os.path.join(SCRIPT_DIR, 'repo')


def get_addon_info(addon_dir):
    xml_path = os.path.join(addon_dir, 'addon.xml')
    tree = ET.parse(xml_path)
    root = tree.getroot()
    addon_id = root.get('id')
    version = root.get('version')
    return addon_id, version, root


def zip_addon(addon_dir, addon_id, version):
    zip_dir = os.path.join(REPO_DIR, addon_id)
    os.makedirs(zip_dir, exist_ok=True)
    zip_path = os.path.join(zip_dir, f'{addon_id}-{version}.zip')

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(addon_dir):
            # Skip __pycache__ and .pyc files
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
    for addon_root in addon_roots:
        addons_root.append(addon_root)

    xml_str = ET.tostring(addons_root, encoding='unicode')
    # Pretty-print
    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str
    return xml_str


def generate_md5(content):
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def main():
    print('Generating Kodi repository...\n')

    addon_roots = []

    for addon_dir in ADDON_SOURCES:
        if not os.path.isdir(addon_dir):
            print(f'WARNING: Addon directory not found, skipping: {addon_dir}')
            continue

        addon_id, version, root = get_addon_info(addon_dir)
        print(f'Processing {addon_id} v{version}')

        zip_addon(addon_dir, addon_id, version)
        addon_roots.append(root)

    print()

    addons_xml = generate_addons_xml(addon_roots)
    addons_xml_path = os.path.join(REPO_DIR, 'addons.xml')
    with open(addons_xml_path, 'w', encoding='utf-8') as f:
        f.write(addons_xml)
    print(f'Generated: {addons_xml_path}')

    md5 = generate_md5(addons_xml)
    md5_path = os.path.join(REPO_DIR, 'addons.xml.md5')
    with open(md5_path, 'w', encoding='utf-8') as f:
        f.write(md5)
    print(f'Generated: {md5_path}')

    print('\nDone! Commit and push the repo/ directory to GitHub.')
    print()
    print('Next steps:')
    print('  1. Update repo/repository.alldebrid/addon.xml with your GitHub username/repo')
    print('  2. Run this script again after updating')
    print('  3. git add repo/ && git commit -m "Update repo" && git push')
    print('  4. In Kodi: Settings → File Manager → Add Source')
    print('     URL: https://raw.githubusercontent.com/GITHUB_USERNAME/GITHUB_REPO/main/repo')
    print('  5. Install repository.alldebrid-1.0.0.zip from that source')
    print('  6. Then install plugin.video.alldebrid from the AllDebrid Cloud Repository')


if __name__ == '__main__':
    main()
