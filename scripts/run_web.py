"""Scheduled-task entry point. Never creates or migrates database tables."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import create_app, serve


def main():
    log_dir = Path(os.environ['LOCALAPPDATA']) / 'ReceivingLog' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'web.log', maxBytes=5_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    serve(create_app())


if __name__ == '__main__':
    main()
