"""Generate the ephemeral nginx gate file without exposing secrets in argv/logs."""

import grp
import os
from pathlib import Path
import re
import subprocess


def gate_record(environment):
    username = environment.get('ADMIN_GATE_USERNAME', '')
    password = environment.get('ADMIN_GATE_PASSWORD', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', username):
        raise ValueError('ADMIN_GATE_USERNAME must be 1-64 letters, digits, dots, underscores or hyphens.')
    if not 24 <= len(password) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in password):
        raise ValueError('ADMIN_GATE_PASSWORD must be 24-128 printable ASCII characters without spaces.')
    # SHA-512 crypt is supported by Debian nginx/libcrypt. Random salt per startup.
    result = subprocess.run(
        ['openssl', 'passwd', '-6', '-stdin'], input=password + '\n',
        text=True, capture_output=True, check=False,
        env={'PATH': '/usr/bin:/bin'},
    )
    hashed = result.stdout.strip()
    if result.returncode or not re.fullmatch(r'\$6\$[./A-Za-z0-9]+\$[./A-Za-z0-9]+', hashed):
        raise ValueError('Admin gate password hashing failed.')
    return f'{username}:{hashed}\n'


def main():
    try:
        record = gate_record(os.environ)
        directory = Path('/run/admin-gate')
        directory.mkdir(mode=0o750, exist_ok=True)
        group = grp.getgrnam('app').gr_gid
        os.chown(directory, 0, group)
        os.chmod(directory, 0o750)
        target = directory / 'htpasswd'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
        with os.fdopen(fd, 'w') as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(record)
    except ValueError as error:
        # Validation messages are fixed strings and never contain secret values.
        raise SystemExit(f'Admin gate configuration failed: {error}') from None
    except OSError as error:
        # Report only the exception class/errno, not paths or subprocess output.
        raise SystemExit(
            f'Admin gate setup failed: {type(error).__name__} (errno {error.errno}); '
            'check OpenSSL availability and permissions for /run/admin-gate.'
        ) from None


if __name__ == '__main__':
    main()
