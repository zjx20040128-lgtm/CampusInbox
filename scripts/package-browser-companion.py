"""Package only the reviewed extension source files; never include secrets."""
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FILES = ['manifest.json', 'parser.js', 'notices.js', 'tasks.js', 'content.js', 'task-content.js', 'background.js', 'options.html', 'options.js', 'options.css', 'README.md']
if __name__ == '__main__':
    target = ROOT / 'artifacts' / 'browser' / 'courseinbox-browser-companion.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES: archive.write(ROOT / 'browser-companion' / name, name)
    print(target)
