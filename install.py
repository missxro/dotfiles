#!/usr/bin/env python3
"""Interactive, reversible user configuration installer. Python standard library only."""
import argparse
import configparser
import cursor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import sys
import uuid
import urllib.request

FASTFETCH_VERSION = '2.70.0'
MIN_I3_VERSION = (4, 22)
FASTFETCH_ASSETS = {
    'amd64': ('amd64', '06e9a1be9a863dc815f8a31a6b1abec7b29967be30084ffcc29c1bca072d801b'),
    'arm64': ('aarch64', '25053651486d97b8731dd6bc59e725944e39adcdcd903741334c1c3282a7281d'),
}


def verify_fastfetch_deb(package, architecture):
    for field, expected in [('Package', 'fastfetch'), ('Architecture', architecture), ('Version', FASTFETCH_VERSION)]:
        value = subprocess.run(['dpkg-deb', '--field', str(package), field],
                               check=True, capture_output=True, text=True, timeout=30).stdout.strip()
        if value != expected:
            raise ValueError(f'Fastfetch {field} mismatch: expected {expected}, got {value}.')


def download_fastfetch(directory, architecture):
    if architecture not in FASTFETCH_ASSETS:
        raise ValueError(f'Official Fastfetch fallback does not support architecture {architecture}.')
    asset, expected = FASTFETCH_ASSETS[architecture]
    url = f'https://github.com/fastfetch-cli/fastfetch/releases/download/{FASTFETCH_VERSION}/fastfetch-linux-{asset}.deb'
    package = directory / 'fastfetch.deb'
    try:
        with urllib.request.urlopen(url, timeout=60) as response, package.open('xb') as output:
            if not response.geturl().startswith('https://'):
                raise ValueError('Fastfetch download redirected outside HTTPS.')
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 50 * 1024 * 1024:
                    raise ValueError('Fastfetch package exceeds download size limit.')
                output.write(chunk)
    except OSError as error:
        raise ValueError(f'Fastfetch download failed: {error}') from error
    if hashlib.sha256(package.read_bytes()).hexdigest() != expected:
        raise ValueError('Fastfetch checksum mismatch; no packages or configuration installed.')
    verify_fastfetch_deb(package, architecture)
    return package

ROOT = Path(__file__).resolve().parent
MODULES = {'core': ['autostart', 'i3', 'kitty', 'nvim', 'picom', 'polybar'],
           'gtk': ['gtk-3.0'], 'qt': ['qt5ct'], 'fastfetch': ['fastfetch']}
BANNER = r'''
 ____   ___ _____ _____ ___ _     _____ ____
|  _ \ / _ \_   _|  ___|_ _| |   | ____/ ___|
| | | | | | || | | |_   | || |   |  _| \___ \
| |_| | |_| || | |  _|  | || |___| |___ ___) |
|____/ \___/ |_| |_|   |___|_____|_____|____/

                  by xro
'''


def plan(modules):
    home = Path.home()
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config')))
    if not config.is_absolute() or config != home / '.config':
        raise ValueError('This rice requires XDG_CONFIG_HOME=$HOME/.config (hardcoded launcher paths).')
    files = []
    for module in modules:
        for name in MODULES[module]:
            for source in sorted((ROOT / 'config' / name).rglob('*')):
                if source.is_file() and '__pycache__' not in source.parts:
                    files.append((source, config / source.relative_to(ROOT / 'config')))
    if 'core' in modules:
        files.extend([(ROOT / 'config/zsh/zshrc', home / '.zshrc'),
                      (ROOT / 'config/zsh/p10k.zsh', home / '.p10k.zsh')])
        theme = ROOT / 'vendor/powerlevel10k'
        files.extend((source, home / '.local/share/debian-i3-dotfiles/powerlevel10k' / source.relative_to(theme))
                     for source in sorted(theme.rglob('*')) if source.is_file())
        files.append((ROOT / 'assets/wallpapers/lain.mp4', home / '.local/share/debian-i3-dotfiles/lain.mp4'))
        files.extend((source, home / '.local/bin' / source.name)
                     for source in sorted((ROOT / 'bin').iterdir()) if source.is_file())
    return files


FONT_FILES = {
    'DepartureMono Nerd Font': 'DepartureMonoNerdFont-Regular.otf',
    'DepartureMono Nerd Font Mono': 'DepartureMonoNerdFontMono-Regular.otf',
}


def font_directory():
    return Path.home() / '.local/share/fonts/departure-mono'


def font_plan(modules, custom_font=None, detect=True):
    if 'core' not in modules or custom_font:
        return []
    families = set()
    if detect and shutil.which('fc-list'):
        try:
            result = subprocess.run(['fc-list', '--format=%{family}\\n'], capture_output=True,
                                    text=True, check=True, timeout=15)
            families = {name.strip() for line in result.stdout.splitlines() for name in line.split(',')}
        except (OSError, subprocess.SubprocessError):
            pass  # Unknown font state: safely install the bundled fonts per-user.
    source = ROOT / 'assets/fonts/departure-mono'
    files = [(source / name, font_directory() / name)
             for family, name in FONT_FILES.items()
             if family not in families and not os.path.lexists(font_directory() / name)]
    if files and not os.path.lexists(font_directory() / 'LICENSE'):
        files.append((source / 'LICENSE', font_directory() / 'LICENSE'))
    return files


def refresh_font_cache():
    directory = font_directory()
    if not directory.is_dir():
        return
    try:
        safe_target(directory / 'probe')
        subprocess.run(['fc-cache', '-f', str(directory)], check=True,
                       capture_output=True, timeout=60)
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Warning: font files are saved, but font cache refresh failed. Run fc-cache -f after installing fontconfig.')


def safe_target(path):
    """Never follow a symlink out of the user's managed destination tree."""
    home = Path.home().absolute()
    if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(home) or path == home:
        raise ValueError('Unsafe destination: ' + str(path))
    for parent in (path, *path.parents):
        if parent == home:
            break
        if parent.is_symlink():
            raise ValueError('Symlink destination; move it aside explicitly first: ' + str(parent))
    if path.exists() and not path.is_file():
        raise ValueError('Destination is not a regular file: ' + str(path))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signature(path):
    return {'sha256': digest(path), 'mode': stat.S_IMODE(path.stat().st_mode)}


def same(source, target):
    return target.is_file() and signature(source) == signature(target)


def validate_state_path(path):
    safe_target(path / 'probe')
    home = Path.home().absolute()
    for parent in (path, *path.parents):
        if parent.exists():
            info = parent.stat()
            if not parent.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('State path must be owned by you and not writable by others: ' + str(parent))
        if parent == home:
            break


def state_path():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'debian-i3-dotfiles'


def state_directory():
    directory = state_path()
    validate_state_path(directory)
    safe_target(directory / 'lock')
    # Create missing ancestors below $HOME as 0700 too: with umask 002 a plain
    # mkdir(parents=True) leaves ~/.local(/state) group-writable and every later
    # run or restore is rejected by validate_state_path().
    home = Path.home().absolute()
    for parent in reversed([p for p in directory.parents if home in p.parents]):
        if not parent.exists():
            parent.mkdir(mode=0o700)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
        raise ValueError('State directory must be private (0700): ' + str(directory))
    return directory


def write_json(path, value):
    with tempfile.NamedTemporaryFile(mode='w', prefix='.manifest-', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(json.dumps(value, indent=2) + '\n')
            output.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def atomic_copy(source, target):
    with tempfile.NamedTemporaryFile(prefix='.dotfiles-', dir=target.parent, delete=False) as output:
        temporary = Path(output.name)
    try:
        shutil.copy2(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def install(files, state):
    changed = [(source, target) for source, target in files if not same(source, target)]
    if not changed:
        print('\nAlready up to date. No files changed; no new backup.')
        return
    safe_target(state / 'backups' / 'probe')
    backup = state / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    (state / 'backups').mkdir(exist_ok=True, mode=0o700)  # parents=True would ignore mode
    backup.mkdir(mode=0o700)
    manifest = {'version': 1, 'home': str(Path.home()), 'entries': [], 'restored': False}
    # Prepare every original and the journal before changing any configuration.
    for index, (source, target) in enumerate(changed):
        original = str(index) if target.exists() else None
        if original is not None:
            shutil.copy2(target, backup / original)
        manifest['entries'].append({'target': str(target), 'original': original,
                                    'original_signature': signature(target) if original is not None else None,
                                    'installed': signature(source)})
    write_json(backup / 'manifest.json', manifest)
    print('\nBackup: ' + str(backup), flush=True)
    print('Restore: ./install.sh --restore ' + str(backup), flush=True)
    try:
        for source, target in changed:
            safe_target(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(source, target)
            print('  Installed ' + str(target))
    except (OSError, KeyboardInterrupt):
        print('Installation interrupted; attempting rollback.', file=sys.stderr)
        restore(backup, False)
        raise
    print('\nDone. Start a new i3 session when ready; nothing was restarted.')


def restore(backup, dry_run):
    backup = backup.expanduser().absolute()
    if backup.parent != state_path() / 'backups':
        raise ValueError('Backup must be in your installer state directory.')
    validate_state_path(backup)
    if state_path().stat().st_mode & 0o077 or backup.stat().st_mode & 0o077:
        raise ValueError('Backup and state directories must be private (0700).')
    safe_target(backup / 'manifest.json')
    if (backup / 'manifest.json').stat().st_uid != os.getuid():
        raise ValueError('Backup manifest must belong to you.')
    allowed = {str(target) for source, target in plan(list(MODULES))}
    allowed.add(str(Path.home() / '.config/debian-i3-dotfiles/wallpaper-path'))
    allowed.add(str(Path.home() / '.local/bin/xwinwrap'))
    manifest = json.loads((backup / 'manifest.json').read_text())
    if manifest.get('version') != 1 or manifest.get('home') != str(Path.home()):
        raise ValueError('Backup version or home does not match this user.')
    if manifest.get('restored'):
        print('This backup has already been restored.')
        return
    for entry in manifest['entries']:
        target = Path(entry['target'])
        cursor_root = Path.home() / '.icons/Kitty'
        cursor_target = (target.is_relative_to(cursor_root) and target != cursor_root)
        font_target = target in {font_directory() / name for name in (*FONT_FILES.values(), 'LICENSE')}
        if str(target) not in allowed and not cursor_target and not font_target and target != Path.home() / '.icons/default/index.theme':
            raise ValueError('Backup destination is not managed by this installer: ' + str(target))
        safe_target(target)
        original = entry['original']
        if original is not None and (not isinstance(original, str) or not original.isdecimal()
                                     or not (backup / original).is_file() or (backup / original).is_symlink()):
            raise ValueError('Invalid backup entry.')
        if original is not None and signature(backup / original) != entry['original_signature']:
            raise ValueError('Backup file is damaged or changed: ' + str(backup / original))
        # Do not silently delete edits made after installation, even with --yes.
        if target.exists() and signature(target) != entry['installed']:
            if original is None or not same(backup / original, target):
                raise ValueError('Changed since install; save/move it before restoring: ' + str(target))
        print('  Restore ' + str(target))
    if dry_run:
        return
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=backup) as folder:
        staged = []
        for number, entry in enumerate(manifest['entries']):
            target = Path(entry['target'])
            current = Path(folder) / str(number) if target.exists() else None
            if current is not None:
                shutil.copy2(target, current)
            staged.append((target, current))
        try:
            for entry in reversed(manifest['entries']):
                target = Path(entry['target'])
                if entry['original'] is None:
                    target.unlink(missing_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    atomic_copy(backup / entry['original'], target)
            manifest['restored'] = True
            write_json(backup / 'manifest.json', manifest)
        except (OSError, KeyboardInterrupt):
            # Atomic manifest replacement is the commit point. An interruption
            # after it must not roll the files back to the installed state.
            persisted = json.loads((backup / 'manifest.json').read_text())
            if persisted.get('restored'):
                raise
            for target, current in staged:
                if current is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_copy(current, target)
            raise
    print('Restored. Backups retained; packages and empty directories are not removed.')


def ask(question, default=False):
    suffix = ' [Y/n] ' if default else ' [y/N] '
    while True:
        try:
            answer = input(question + suffix).strip().lower()
        except EOFError as error:
            raise ValueError('Input ended. Use --yes for unattended file-only installation.') from error
        if not answer:
            return default
        if answer in ('y', 'yes', 's', 'si', 'sí'):
            return True
        if answer in ('n', 'no'):
            return False
        print('Please answer y or n.')


def xwinwrap_available():
    """Match the launcher: ~/.local/bin/xwinwrap counts even when it is not on PATH."""
    local = Path.home() / '.local/bin/xwinwrap'
    return bool(shutil.which('xwinwrap')) or (local.is_file() and os.access(local, os.X_OK))


def package_names(modules, distro=None):
    packages = []
    if 'core' in modules:
        for line in (ROOT / 'packages/debian.txt').read_text().splitlines():
            packages.extend(line.split('#', 1)[0].split())
    for module, names in {'gtk': ['lxappearance', 'adwaita-icon-theme'],
                          'qt': ['qt5ct'], 'fastfetch': ['fastfetch']}.items():
        if module in modules:
            packages.extend(names)
    if 'core' in modules and not xwinwrap_available():
        packages.extend(['build-essential', 'libx11-dev', 'libxext-dev', 'libxrender-dev'])
    profile = PACKAGE_PROFILES.get(distro or '', {})
    return list(dict.fromkeys(profile.get(name, name) for name in packages))


# Package profiles use the shared apt backend; exact IDs only, never ID_LIKE.
PACKAGE_PROFILES = {
    'debian': {},
    'ubuntu': {},
    'kali': {},
    'parrot': {},
}


OS_RELEASE = Path('/etc/os-release')


def read_os_release():
    return OS_RELEASE.read_text()


def parse_os_release(text):
    """Parse the KEY=VALUE subset needed here; never evaluate shell syntax."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if not key.replace('_', '').isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def check_system():
    if os.geteuid() == 0:
        raise ValueError('Run as your desktop user, not root. Only apt uses sudo.')
    info = parse_os_release(read_os_release())
    distro, version = info.get('ID'), info.get('VERSION_ID')
    version_ok = (distro == 'debian' and version == '13'
                  or distro == 'ubuntu' and version in {'22.04', '24.04', '26.04'}
                  or distro == 'kali' and version == 'rolling'
                  or distro == 'parrot' and bool(version and version.split('.', 1)[0] in {'6', '7'}
                                               and all(part.isascii() and part.isdigit() for part in version.split('.'))))
    supported = distro in PACKAGE_PROFILES and version_ok
    if not supported:
        raise ValueError('Package setup supports Debian 13 and Ubuntu 22.04/24.04/26.04. Kali and Parrot package candidates are provisional; use --files-only elsewhere.')
    if distro == 'ubuntu' and version in {'22.04', '24.04', '26.04'}:
        print('Ubuntu package setup requires the official Universe component enabled; missing candidates are checked before installation.')
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        print('You are using Wayland. Installation is allowed; select an X11/i3 session after logging out.')
    return distro


def xwinwrap_plan(staging):
    """Compile pinned source as the user; installation remains transactional."""
    source = ROOT / 'vendor/xwinwrap/xwinwrap.c'
    if hashlib.sha256(source.read_bytes()).hexdigest() != '00b7ec706bad901a3d224653575d8d05e878e3b4535844a624f73ceff29e04e8':
        raise ValueError('Bundled xwinwrap source checksum mismatch.')
    compiler = shutil.which('cc')
    if not compiler:
        raise ValueError('Building xwinwrap requires build-essential and X11 development packages. Approve the package step.')
    binary = staging / 'xwinwrap'
    subprocess.run([compiler, '-O2', '-Wall', str(source), '-o', str(binary),
                    '-lX11', '-lXext', '-lXrender'], check=True, timeout=120)
    binary.chmod(0o755)
    return [(binary, Path.home() / '.local/bin/xwinwrap')]


SUR5R_KEY_VERSION = '2025.12.14'
SUR5R_KEY_HASH = '2c816fbd12ea4d84811818aed0ce3a5da589be1afa30833eb32abc1e4fe6349e'
SUR5R_SOURCE = Path('/etc/apt/sources.list.d/sur5r-i3.list')
SUR5R_PREFERENCES = Path('/etc/apt/preferences.d/sur5r-i3')
SUR5R_PINS = ('Package: i3 i3-wm i3status i3lock sur5r-keyring\n'
              'Pin: origin debian.sur5r.net\nPin-Priority: 500\n\n'
              'Package: *\nPin: origin debian.sur5r.net\nPin-Priority: -1\n')


def sur5r_source(version):
    codename = {'22.04': 'jammy', '24.04': 'noble'}.get(version)
    if not codename:
        raise ValueError('sur5r repository is only enabled for Ubuntu 22.04/24.04.')
    return f'deb [signed-by=/usr/share/keyrings/sur5r-keyring.gpg] https://debian.sur5r.net/i3/ {codename} universe\n'


def check_repository_target(path, expected):
    if path.is_symlink():
        raise ValueError(f'Refusing symlinked repository configuration: {path}')
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'Unsafe existing repository configuration: {path}')
        if path.read_text() != expected:
            raise ValueError(f'Refusing to overwrite existing repository configuration: {path}')


def approve_sur5r(version):
    source = sur5r_source(version)
    check_repository_target(SUR5R_SOURCE, source)
    check_repository_target(SUR5R_PREFERENCES, SUR5R_PINS)
    print('Native i3 is too old. Optional repository recommended by i3: https://debian.sur5r.net/i3/')
    print(f'Install verified sur5r-keyring {SUR5R_KEY_VERSION}; write {SUR5R_SOURCE} and {SUR5R_PREFERENCES}.')
    print('signed-by limits the signing key; apt pinning limits this origin to i3 packages and its keyring.')
    print('These system changes persist after dotfiles restore. No running session will be restarted.')
    if not ask('Add this signed repository and install compatible i3?', default=False):
        raise ValueError('Repository declined. Core requires i3 >= 4.22; no configuration was placed.')
    return source


def download_sur5r_key(directory):
    package = directory / 'sur5r-keyring.deb'
    url = f'https://debian.sur5r.net/i3/pool/main/s/sur5r-keyring/sur5r-keyring_{SUR5R_KEY_VERSION}_all.deb'
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            if not response.geturl().startswith('https://'):
                raise ValueError('Keyring download must use HTTPS.')
            data = response.read(2 * 1024 * 1024 + 1)
    except OSError as error:
        raise ValueError(f'Keyring download failed: {error}') from error
    if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != SUR5R_KEY_HASH:
        raise ValueError('sur5r keyring checksum mismatch; no system changes made.')
    package.write_bytes(data)
    for field, expected in [('Package', 'sur5r-keyring'), ('Version', SUR5R_KEY_VERSION), ('Architecture', 'all')]:
        value = subprocess.run(['dpkg-deb', '--field', str(package), field], check=True,
                               capture_output=True, text=True, timeout=30).stdout.strip()
        if value != expected:
            raise ValueError(f'sur5r keyring {field} mismatch; no system changes made.')
    return package


def install_sur5r(directory, package, source):
    # Recheck immediately before privileged writes; never overwrite custom content.
    check_repository_target(SUR5R_SOURCE, source)
    check_repository_target(SUR5R_PREFERENCES, SUR5R_PINS)
    subprocess.run(['sudo', 'apt-get', 'install', str(package)], check=True)
    for name, target, content in [('sur5r-i3.list', SUR5R_SOURCE, source),
                                   ('sur5r-i3.pref', SUR5R_PREFERENCES, SUR5R_PINS)]:
        staged = directory / name
        staged.write_text(content)
        subprocess.run(['sudo', 'install', '-o', 'root', '-g', 'root', '-m', '0644',
                        str(staged), str(target)], check=True)
    print('Repository configured. If a later apt step fails, these repository/keyring changes remain; dotfiles restore does not remove them.')


def setup_packages(modules, enabled, distro=None):
    build = 'core' in modules and not xwinwrap_available()
    if not enabled:
        print('Package installation skipped (--yes never grants permission for apt).')
        return
    if 'core' in modules and shutil.which('i3') is None:
        print('i3 is missing. This step installs it; an existing i3 session is not required.')
    packages = package_names(modules, distro)
    if build:
        print('xwinwrap is missing: after package approval, compile the bundled pinned source into ~/.local/bin/xwinwrap (no sudo build).')
    print('\nDebian packages: ' + ' '.join(packages))
    if 'fastfetch' in packages:
        print(f'If apt has no Fastfetch candidate, download official fastfetch-cli/fastfetch {FASTFETCH_VERSION} .deb from GitHub (amd64/arm64), verify pinned SHA256 and package metadata, then install with apt. No PPA is added.')
    if 'core' in modules:
        print('i3 must be version 4.22 or newer for this configuration (gaps and tiling_drag). Ubuntu native i3 may be too old; a signed repository is offered separately with default-no approval.')
    print('Only package and approved repository setup is elevated. No login-shell changes, display-manager changes or service restarts are requested.')
    if not ask('Run sudo apt-get update, then sudo apt-get install for these packages?', default=True):
        return
    if not shutil.which('sudo') or not shutil.which('apt-get') or not shutil.which('apt-cache'):
        raise ValueError('sudo/apt-get/apt-cache unavailable. Ask your administrator to install the listed packages.')
    distro = distro or check_system()
    missing = preflight_packages(packages)
    unavailable = [name for name in missing if name != 'fastfetch']
    if unavailable:
        raise ValueError('No apt candidate for: ' + ', '.join(unavailable) + '. Enable the appropriate official repository components and refresh apt metadata; no repositories were changed.')
    repository_source = None
    if 'core' in modules and distro == 'ubuntu' and not i3_version_supported(apt_candidate('i3-wm')):
        repository_source = approve_sur5r(os_release_version())
    # Private staging prevents replacement of a verified package by other users.
    # apt may report its standard unsandboxed-local-file warning because _apt
    # cannot traverse this directory. Never weaken the sandbox configuration.
    with tempfile.TemporaryDirectory(prefix='dotfiles-fastfetch-') as folder:
        install_packages = list(packages)
        if 'fastfetch' in missing:
            architecture = subprocess.run(['dpkg', '--print-architecture'], check=True,
                                          capture_output=True, text=True, timeout=30).stdout.strip()
            package = download_fastfetch(Path(folder), architecture)
            install_packages = [str(package) if name == 'fastfetch' else name for name in packages]
        if repository_source:
            keyring = download_sur5r_key(Path(folder))
            install_sur5r(Path(folder), keyring, repository_source)
        subprocess.run(['sudo', 'apt-get', 'update'], check=True)
        if repository_source and not i3_version_supported(apt_candidate('i3-wm')):
            raise ValueError('Repository added but i3 candidate is still older than 4.22. No dotfiles were placed; inspect apt policy i3-wm.')
        # Do not use -y: apt displays its actual transaction and requests approval.
        subprocess.run(['sudo', 'apt-get', 'install', *install_packages], check=True)
    return build


def apt_candidate(package):
    result = subprocess.run(['apt-cache', 'policy', package], capture_output=True,
                            text=True, check=False, env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        if line.strip().startswith('Candidate:'):
            value = line.split(':', 1)[1].strip()
            return None if value == '(none)' else value
    return None


def os_release_version():
    return parse_os_release(read_os_release()).get('VERSION_ID')


def i3_version_supported(version):
    if not version:
        return False
    import re
    match = re.search(r'(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?', version)
    return bool(match and tuple(int(part or 0) for part in match.groups()) >= (*MIN_I3_VERSION, 0))


def validate_i3_config(config, binary=None):
    """Run i3's parser without starting a session or executing config commands."""
    binary = binary or shutil.which('i3')
    if not binary:
        raise ValueError('Cannot validate i3 configuration: i3 is not installed. No configuration was placed.')
    version = subprocess.run([binary, '--version'], capture_output=True, text=True,
                             check=True, timeout=15).stdout
    if not i3_version_supported(version):
        raise ValueError(f'Core requires i3 >= 4.22 for gaps and tiling_drag; found {version.strip() or "unknown version"}. No configuration was placed.')
    result = subprocess.run([binary, '-C', '-c', str(config)], capture_output=True,
                            text=True, check=False, timeout=30)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError('i3 rejected the configuration; no configuration was placed: ' + detail)


def preflight_packages(packages, policy=None):
    """Return missing apt candidates; injectable policy makes this offline-testable."""
    policy = policy or (lambda name: subprocess.run(
        ['apt-cache', 'policy', name], capture_output=True, text=True, check=False,
        env={**os.environ, 'LC_ALL': 'C'}))
    missing = []
    for package in packages:
        result = policy(package)
        candidate = any(line.strip().startswith('Candidate:') and
                        line.strip() != 'Candidate: (none)'
                        for line in result.stdout.splitlines())
        if result.returncode != 0 or not candidate:
            missing.append(package)
    return missing


def diagnostics(modules):
    print('\nDependency check:')
    commands = ['i3', 'i3lock', 'xss-lock', 'polybar', 'kitty', 'picom', 'dmenu_run', 'dex', 'cava', 'xrandr', 'pactl', 'zsh'] if 'core' in modules else []
    if 'fastfetch' in modules:
        commands.append('fastfetch')
    for command in commands:
        print(f"  {'OK     ' if shutil.which(command) else 'MISSING'} {command}")
    if 'core' in modules:
        for module in ('dbus', 'gi'):
            result = subprocess.run(['/usr/bin/python3', '-c', '__import__(' + repr(module) + ')'],
                                    capture_output=True, text=True)
            print(f"  {'OK     ' if result.returncode == 0 else 'MISSING'} python3-{module}")
        print('  DepartureMono fonts are bundled and installed per-user if missing. Graphite-Dark is external; Kitty cursor is optional.')
        print('  No remote installer or unpinned third-party download is executed.')
    if 'qt' in modules:
        print('  Qt: set QT_QPA_PLATFORMTHEME=qt5ct in your session environment if needed (not overwritten).')


def prepare(files, args, staging):
    """Customize copies, never the versioned originals."""
    result = []
    for index, (source, target) in enumerate(files):
        if source.name == 'settings.ini' and source.parent.name == 'gtk-3.0' and not getattr(args, 'cursor', False):
            settings = configparser.ConfigParser(interpolation=None)
            settings.read_string(source.read_text())
            previous = configparser.ConfigParser(interpolation=None)
            safe_target(target)
            if target.exists():
                previous.read_string(target.read_text())
            for key in ('gtk-cursor-theme-name', 'gtk-cursor-theme-size'):
                settings.remove_option('Settings', key)
                if previous.has_option('Settings', key):
                    settings.set('Settings', key, previous.get('Settings', key))
            copy = staging / str(index)
            with copy.open('w') as output:
                settings.write(output)
            source = copy
        elif source.name == 'kitty.conf' and (args.font or args.shell):
            text = source.read_text()
            if args.font:
                text = text.replace('font_family DepartureMono Nerd Font Mono', 'font_family ' + args.font)
            if args.shell:
                text = text.replace('shell zsh', 'shell ' + args.shell)
            copy = staging / str(index)
            copy.write_text(text)
            copy.chmod(stat.S_IMODE(source.stat().st_mode))
            source = copy
        elif source.name == 'config' and source.parent.name == 'i3' and args.font:
            copy = staging / str(index)
            copy.write_text(source.read_text().replace('font pango:DepartureMono Nerd Font 12',
                                                       'font pango:' + args.font + ' 12'))
            copy.chmod(stat.S_IMODE(source.stat().st_mode))
            source = copy
        elif source.name == 'config.ini' and source.parent.name == 'polybar' and args.font:
            text = source.read_text().replace('DepartureMono Nerd Font Mono:size=13', args.font + ':size=13')
            copy = staging / str(index)
            copy.write_text(text)
            copy.chmod(stat.S_IMODE(source.stat().st_mode))
            source = copy
        result.append((source, target))
    if getattr(args, 'cursor', False):
        archive = staging / 'Kitty.tar.gz'
        cursor.download(archive)
        result.extend(cursor.unpack(archive, staging / 'cursor'))
        default = staging / 'cursor-default'
        default.write_text('[Icon Theme]\nInherits=Kitty\n')
        result.append((default, Path.home() / '.icons/default/index.theme'))
        gtk_target = Path.home() / '.config/gtk-3.0/settings.ini'
        gtk_source = next((s for s, t in result if t == gtk_target), gtk_target)
        safe_target(gtk_target)
        settings = configparser.ConfigParser(interpolation=None)
        if gtk_source.exists():
            settings.read_string(gtk_source.read_text())
        if not settings.has_section('Settings'):
            settings.add_section('Settings')
        settings.set('Settings', 'gtk-cursor-theme-name', 'Kitty')
        settings.set('Settings', 'gtk-cursor-theme-size', '48')
        configured = staging / 'cursor-gtk.ini'
        with configured.open('w') as output:
            settings.write(output)
        result = [(s, t) for s, t in result if t != gtk_target]
        result.append((configured, gtk_target))
    bundled_video = Path.home() / '.local/share/debian-i3-dotfiles/lain.mp4'
    has_bundled = any(target == bundled_video for _, target in result)
    if args.wallpaper or has_bundled:
        video = args.wallpaper.expanduser().resolve() if args.wallpaper else bundled_video
        if args.wallpaper and (not video.is_file() or '\n' in str(video)):
            raise ValueError('Wallpaper must be an existing local video file.')
        staged_xwinwrap = any(target == Path.home() / '.local/bin/xwinwrap' for _, target in result)
        missing = [name for name in ('mpv', 'xwinwrap')
                   if not (xwinwrap_available() if name == 'xwinwrap' else shutil.which(name))
                   and not (name == 'xwinwrap' and staged_xwinwrap)]
        if missing and not args.wallpaper:
            print('Wallpaper saved. Playback requires: ' + ', '.join(missing) + '.')
        if missing and args.wallpaper:
            raise ValueError('Video wallpaper needs: ' + ', '.join(missing) + '. Install them separately or skip --wallpaper.')
        source = staging / 'wallpaper-path'
        source.write_text(str(video) + '\n')
        result.append((source, Path.home() / '.config/debian-i3-dotfiles/wallpaper-path'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Print planned files; never write or install packages.')
    parser.add_argument('--modules', default='core,fastfetch', help='Comma-separated: core,gtk,qt,fastfetch')
    parser.add_argument('--yes', action='store_true', help='Accept file installation/restore; does not install packages.')
    parser.add_argument('--files-only', action='store_true', help='Only copy files; skip OS/dependency setup.')
    parser.add_argument('--restore', type=Path, help='Restore a backup directory, refusing later local edits.')
    parser.add_argument('--font', help='Installed font family for Kitty and Polybar; no font download.')
    parser.add_argument('--shell', choices=['zsh', 'bash'], help='Kitty shell only; never runs chsh.')
    parser.add_argument('--wallpaper', type=Path, help='Existing local video; requires mpv and xwinwrap.')
    parser.add_argument('--cursor', action='store_true', help='Download and apply the checksum-pinned Kitty cursor.')
    parser.add_argument('--no-cursor', action='store_true', help='Skip the initial cursor question and preserve the current cursor.')
    args = parser.parse_args()
    if args.cursor and args.no_cursor:
        parser.error('--cursor and --no-cursor are mutually exclusive.')
    for value in (args.font,):
        if value is not None and (not value.strip() or any(char in value for char in '\n\r;=')):
            parser.error('Invalid font family.')
    print(BANNER)
    if args.restore:
        if not args.dry_run and not args.yes and not ask('Restore this backup (later local edits will be refused)?'):
            print('Cancelled. No files changed.')
            return 0
        if args.dry_run:
            restore(args.restore, True)
        else:
            state = state_directory()
            with (state / 'lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                restore(args.restore, False)
                refresh_font_cache()
        return 0
    modules = list(dict.fromkeys(args.modules.split(',')))
    if any(module not in MODULES for module in modules):
        parser.error('Unknown module; choose core,gtk,qt,fastfetch.')
    if not args.dry_run and not args.yes and not args.cursor and not args.no_cursor:
        args.cursor = ask('Download and apply my Kitty cursor (black cat, by Noiire; Linux port by pxryzl)?', default=True)
    if not args.dry_run and not args.yes and args.modules == 'core,fastfetch':
        print('Core: i3 + Polybar + Picom + Kitty + wallpaper helpers + Fastfetch with bundled artwork.')
        for module, label in [('gtk', 'GTK appearance (requires Graphite-Dark; cursor is selected separately)'),
                              ('qt', 'Qt settings (qt5ct)')]:
            if ask('Include ' + label + '?'):
                modules.append(module)
    if args.wallpaper and 'core' not in modules:
        parser.error('--wallpaper requires core.')
    # Do not invoke Fontconfig until approval: even fc-list can create caches.
    files = plan(modules) + font_plan(modules, args.font, detect=False)
    if 'core' in modules and not args.font:
        print('Fonts: possible placements listed below; after approval, installed families and existing destination files are preserved.')
    for source, target in files:
        safe_target(target)
        print(f'  {source.relative_to(ROOT)} -> {target}')
    if args.dry_run:
        if args.cursor:
            print('Cursor: download verified Kitty archive; install ~/.icons/Kitty; configure ~/.icons/default/index.theme and GTK cursor settings (not downloaded or written).')
        print('\nPackages (not executed): ' + ' '.join(package_names(modules, 'debian')))
        print(f'Font: {args.font or "DepartureMono Nerd Font Mono"}; Kitty shell: {args.shell or "zsh"}')
        if args.wallpaper:
            print('Wallpaper path (not written): ' + str(args.wallpaper))
        return 0
    if not args.yes and not ask('Apply this selection? Existing managed files will be backed up.'):
        print('Cancelled. No files changed.')
        return 0
    build_xwinwrap = False
    if not args.files_only:
        distro = check_system()
        build_xwinwrap = setup_packages(modules, enabled=not args.yes, distro=distro)
        diagnostics(modules)
        if 'core' in modules and not args.yes:
            if not args.shell and not shutil.which('zsh'):
                if ask('zsh is missing. Use bash in Kitty?', default=True):
                    args.shell = 'bash'
                else:
                    raise ValueError('Install zsh or choose --shell bash before installing core.')
    files = [pair for pair in files if pair[1].parent != font_directory()] + font_plan(modules, args.font)
    with tempfile.TemporaryDirectory(prefix='dotfiles-') as folder:
        if build_xwinwrap:
            target = Path.home() / '.local/bin/xwinwrap'
            safe_target(target)
            if os.path.lexists(target):
                raise ValueError('Existing ~/.local/bin/xwinwrap is not an executable file; remove or fix it before retrying.')
            files.extend(xwinwrap_plan(Path(folder)))
        files = prepare(files, args, Path(folder))
        if 'core' in modules and not args.files_only:
            i3_config = next((source for source, target in files
                              if target == Path.home() / '.config/i3/config'),
                             ROOT / 'config/i3/config')
            validate_i3_config(i3_config)
        for source, target in files:
            safe_target(target)
        state = state_directory()
        with (state / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            install(files, state)
            if any(target.parent == font_directory() for _, target in files):
                refresh_font_cache()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, EOFError) as error:
        print(f'Error: {error}', file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('\nCancelled.', file=sys.stderr)
        raise SystemExit(130)
