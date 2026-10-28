"""Launcher SENTINEL: siapkan .venv + dependensi, lalu jalankan app.py dalam satu perintah.

Contoh:  python start.py
"""
import argparse
import os
import pathlib
import shutil
import socket
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
VENV = ROOT / '.venv'
MARKER = 'SENTINEL_VENV'


def venv_python():
    return VENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def in_venv():
    return sys.prefix != getattr(sys, 'base_prefix', sys.prefix)


def ensure_venv():
    """Re-exec di dalam .venv bila perlu. Mengembalikan exit code atau None."""
    if os.environ.get(MARKER) == '1' or in_venv():
        return None
    py = venv_python()
    if not py.exists():
        print('Membuat virtualenv .venv ...')
        try:
            subprocess.check_call([sys.executable, '-m', 'venv', str(VENV)])
        except (subprocess.CalledProcessError, OSError) as e:
            print(f'[peringatan] gagal membuat .venv ({e}); memakai Python saat ini.')
            return None
    if not py.exists():
        print('[peringatan] Python di .venv tidak ditemukan; memakai Python saat ini.')
        return None
    env = dict(os.environ, **{MARKER: '1'})
    return subprocess.call([str(py), str(pathlib.Path(__file__).resolve()), *sys.argv[1:]],
                           cwd=str(ROOT), env=env)


def install(py, optional=True):
    print('Memasang dependensi inti ...')
    if subprocess.call([py, '-m', 'pip', 'install', '-q', '-r', str(ROOT / 'requirements.txt')]) != 0:
        raise SystemExit('Gagal memasang requirements.txt. Periksa koneksi/pip lalu coba lagi.')
    if not optional:
        return
    req = ROOT / 'requirements-optional.txt'
    if not req.exists():
        return
    print('Memasang pustaka opsional (best-effort) ...')
    if subprocess.call([py, '-m', 'pip', 'install', '-q', '-r', str(req)]) != 0:
        print('[peringatan] pustaka opsional gagal dipasang; TikTok/Instagram/Facebook publik')
        print('             mungkin tidak tersedia. Aplikasi tetap dijalankan.')


def prepare_env():
    env_file = ROOT / '.env'
    if env_file.exists():
        return
    try:
        shutil.copyfile(ROOT / '.env.example', env_file)
        print('Membuat .env dari .env.example (semua isian opsional).')
    except OSError as e:
        print(f'[peringatan] tidak bisa membuat .env: {e}')


def run_tests(py):
    for name in ('tests/test_public.py',):
        print(f'Menjalankan {name} ...')
        if subprocess.call([py, str(ROOT / name)], cwd=str(ROOT)) != 0:
            raise SystemExit(f'Uji gagal: {name}; start dibatalkan.')
    print('Semua uji lulus.')


def main():
    ap = argparse.ArgumentParser(description='Jalankan SENTINEL (dashboard + engine) dalam satu perintah.')
    ap.add_argument('--no-install', action='store_true', help='lewati pemasangan dependensi')
    ap.add_argument('--no-venv', action='store_true', help='jangan membuat/memakai .venv')
    ap.add_argument('--no-optional', action='store_true', help='lewati pustaka opsional')
    ap.add_argument('--no-browser', action='store_true', help='jangan buka browser otomatis')
    ap.add_argument('--host', help='alamat bind (bawaan 127.0.0.1)')
    ap.add_argument('--port', help='port dashboard (bawaan 8787)')
    ap.add_argument('--test', action='store_true', help='jalankan uji lebih dulu, batal bila gagal')
    args = ap.parse_args()

    if sys.version_info < (3, 9):
        raise SystemExit('SENTINEL butuh Python 3.9 atau lebih baru.')

    if not args.no_venv:
        code = ensure_venv()
        if code is not None:
            raise SystemExit(code)

    if not args.no_install:
        install(sys.executable, optional=not args.no_optional)
    prepare_env()

    if args.test:
        run_tests(sys.executable)

    env = dict(os.environ)
    if args.host:
        env['HOST'] = args.host
    if args.port:
        env['PORT'] = str(args.port)
    if args.no_browser:
        env['OPEN_BROWSER'] = '0'
    host, port = env.get('HOST', '127.0.0.1'), env.get('PORT', '8787')
    try:
        probe = host if host in ('127.0.0.1', 'localhost') else '127.0.0.1'
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            busy = s.connect_ex((probe, int(port))) == 0
    except (ValueError, OSError):
        busy = False
    if busy:
        print(f'[peringatan] Port {port} sudah dipakai. Kemungkinan instance SENTINEL lama masih berjalan.')
        print(f'             Hentikan instance itu (Ctrl+C) atau jalankan: python start.py --port {int(port) + 1}')
        raise SystemExit(1)
    print(f'Menjalankan SENTINEL di http://{host}:{port} (Ctrl+C untuk berhenti)')
    try:
        code = subprocess.call([sys.executable, str(ROOT / 'app.py')], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)


if __name__ == '__main__':
    main()
