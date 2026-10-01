"""Windows launcher / build helper. Uses a project-local virtual environment."""
from pathlib import Path
import importlib.metadata
import os
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv'
PYTHON = ENV / 'Scripts' / 'python.exe'


def run(*args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def prepare():
    if sys.platform != 'win32':
        raise RuntimeError('This helper must run on Windows 10/11 x64.')
    if not (3, 11) <= sys.version_info[:2] <= (3, 13) or sys.maxsize <= 2**32:
        raise RuntimeError('Install Python 3.11, 3.12 or 3.13 (64-bit), then run START.bat.')
    if not PYTHON.is_file():
        print('Creating local Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(ENV)
    # Skip downloads on later starts when the pinned version is already installed.
    result = subprocess.run([
        str(PYTHON), '-c',
        "import importlib.metadata; assert importlib.metadata.version('PySide6') == '6.8.3'",
    ], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        print('Downloading interface libraries. Internet is needed only for this setup.', flush=True)
        run(PYTHON, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt')
    run(PYTHON, ROOT / 'main.py', '--check')


def build():
    run(PYTHON, '-m', 'pip', 'install', '-r', ROOT / 'requirements-build.txt')
    run(PYTHON, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
        '--noupx', '--name', 'MirPrompt', '--icon', ROOT / 'ui' / 'app.ico',
        '--add-data', f'{ROOT / "ui"};ui', '--add-data', f'{ROOT / "tasks.json"};.',
        ROOT / 'main.py')
    target = ROOT / 'dist' / 'MirPrompt'
    shutil.copy2(ROOT / 'PORTABLE_README.txt', target / 'README.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.txt', target / 'THIRD_PARTY_NOTICES.txt')
    for name in ('config.json', 'settings.py', 'collect_results.py', 'ranking_excel.py',
                 'COLLECT_RESULTS.bat', 'NETWORK_SETUP.md'):
        shutil.copy2(ROOT / name, target / name)
    (target / 'results').mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'results' / 'README.txt', target / 'results' / 'README.txt')
    bundle = shutil.make_archive(str(ROOT / 'MirPrompt_Portable_Windows'), 'zip',
                                root_dir=ROOT / 'dist', base_dir='MirPrompt')
    print(f'Portable application: {target / "MirPrompt.exe"}')
    print(f'Copy the WHOLE MirPrompt directory, or use this archive: {bundle}')


def main():
    prepare()
    if '--build' in sys.argv:
        build()
    else:
        run(PYTHON, ROOT / 'main.py', *(['--fullscreen'] if '--fullscreen' in sys.argv else []))


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
        print(f'\nERROR: {error}', file=sys.stderr)
        print('See README.md for setup and troubleshooting.', file=sys.stderr)
        sys.exit(1)
