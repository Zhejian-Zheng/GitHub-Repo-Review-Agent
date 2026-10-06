"""Run migration/transaction tests in a temporary PostgreSQL cluster, then stop it."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

pg_bin = Path(os.environ.get('PG_BINDIR', '/opt/homebrew/opt/postgresql@16/bin'))
if not (pg_bin / 'initdb').exists():
    pg_bin = Path(shutil.which('initdb') or '/missing/initdb').parent
with tempfile.TemporaryDirectory(prefix='review-pg-') as directory:
    root = Path(directory)
    data, socket = root / 'data', root / 'socket'
    socket.mkdir()
    subprocess.run([str(pg_bin / 'initdb'), '-D', str(data), '--auth=trust', '--no-locale', '-E', 'UTF8'], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(pg_bin / 'pg_ctl'), '-D', str(data), '-l', str(root / 'postgres.log'), '-o',
                    f"-F -k {socket} -c listen_addresses='' -p 54231", '-w', 'start'], check=True, stdout=subprocess.DEVNULL)
    try:
        subprocess.run([str(pg_bin / 'createdb'), '-h', str(socket), '-p', '54231', 'repo_review_test'], check=True)
        env = dict(os.environ, REPO_REVIEW_TEST_DATABASE_URL=f'host={socket} port=54231 dbname=repo_review_test')
        code = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/integration', '-v'], env=env).returncode
    finally:
        subprocess.run([str(pg_bin / 'pg_ctl'), '-D', str(data), '-m', 'immediate', '-w', 'stop'], check=True, stdout=subprocess.DEVNULL)
    sys.exit(code)
