#!/bin/bash
# Rebuild (writes index.html at repo root with assets/ paths) and push to GitHub Pages
set -e
cd /workspace/x-digests && python3 build.py && git add -A index.html assets cache digests site build.py add_digest.py publish.sh .gitignore .nojekyll preview.png && git -c user.name="mohammadsadekbezri-cmd" -c user.email="mohammadsadekbezri-cmd@users.noreply.github.com" commit -qm "Digest update $(date +%F)" && git push -q
