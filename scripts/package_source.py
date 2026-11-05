"""Create a source-only ZIP; exclude runtime state and check known local secrets."""
import argparse
import fnmatch
import shlex
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {'.git', '.venv', 'var', 'staticfiles', '__pycache__', '.pytest_cache', 'test-results', 'dist'}


def source_files():
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDED for part in rel.parts) or not path.is_file() or path.is_symlink():
            continue
        if path.name != '.env.example' and (path.name == '.env' or path.name.startswith('.env.')):
            continue
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in ('*.pyc', '*.sqlite3', '*.zip')):
            continue
        yield path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        raise SystemExit('Put the archive outside the checkout.')
    secrets = []
    for config in (ROOT / 'var').glob('*.env'):
        for line in config.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                if any(word in key for word in ('PASSWORD', 'SECRET_KEY', 'DATABASE_URL')):
                    values = shlex.split(value)
                    if values and len(values[0]) >= 12:
                        secrets.append(values[0].encode())
    files = list(source_files())
    for path in files:
        content = path.read_bytes()
        if any(secret in content for secret in secrets):
            raise SystemExit('Known local credential found in ' + str(path.relative_to(ROOT)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path('Student_Cabinet') / path.relative_to(ROOT))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        assert not any('/var/' in name or '/.git/' in name or '/.venv/' in name for name in archive.namelist())
    print(f'Packaged {len(files)} files; ZIP integrity OK; known local secrets absent; runtime state excluded.')
