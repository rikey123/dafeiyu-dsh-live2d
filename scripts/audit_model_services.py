"""Manage real model services for one isolated acceptance database.

Run in the supervisor environment (.venv), which owns pywin32 containment.
No primary database, cloud provider or ASR process is touched.
"""
import argparse
import os
from pathlib import Path
import sys
import time

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run import healthy
from voice_services import VoiceServiceManager, desired_voice_services, saved_voice_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--stop-file', type=Path, required=True)
    args = parser.parse_args()
    directory = args.data_dir.resolve(strict=True)
    if directory == (ROOT / 'data').resolve() or not (directory / 'companion.sqlite3').is_file():
        raise ValueError('Requires an initialized isolated acceptance database')
    env = {**{k: v for k, v in dotenv_values(ROOT / '.env').items() if v is not None}, **os.environ,
           'DAFEIYU_DATA_DIR': str(directory)}
    manager = VoiceServiceManager(ROOT, healthy)
    try:
        while directory.exists() and not args.stop_file.exists():
            updated = env.copy()
            _, kinds = desired_voice_services(saved_voice_settings(ROOT, updated), updated)
            manager.sync(updated, kinds)
            time.sleep(.5)
    finally:
        manager.close()


if __name__ == '__main__':
    main()
