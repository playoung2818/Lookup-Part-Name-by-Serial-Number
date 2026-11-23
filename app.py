from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import logging
import os
import re
import secrets
import socket
import sys
from dateutil.parser import parse
from config import Config


from models.models import db, ReceivingLog
from functions.utils import (
    extract_useful_number,
    get_part_name_from_db,
    extract_product_details_from_word,
    validate_sn_part_matches_via_api
)
from routes.Index_Routes import index_bp
from routes.Api_Routes import api_bp
from routes.Work_Order_Routes import work_orders_bp
from routes.Borrow_Log_Routes import borrow_log_bp
from routes.Inventory_Count_Routes import inventory_count_bp
from routes.Receiving_Routes import receiving_bp

def create_app(test_config=None):
    """Application factory — makes testing & deployment easier."""
    app = Flask(__name__,
                template_folder="templates",
                static_folder="static")
    app.config.from_object(Config)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    if test_config:
        app.config.update(test_config)

    # initialize SQLAlchemy
    db.init_app(app)

    # register modular routes
    app.register_blueprint(index_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(borrow_log_bp)
    app.register_blueprint(inventory_count_bp)
    app.register_blueprint(receiving_bp)
    # Signed preview forms can exceed Flask's default 500 KB field limit.
    app.config['MAX_FORM_MEMORY_SIZE'] = 10 * 1024 * 1024

    @app.get('/health')
    def health():
        """Used by scripts/start_web_desktop.ps1: can THIS process open the file shares?"""
        shares = {share: share_reachable(share) for share in app.config.get('REQUIRED_SHARES', [])}
        response = jsonify(ok=all(shares.values()), pid=os.getpid(), shares=shares)
        response.headers['Cache-Control'] = 'no-store'
        return response

    return app


def share_reachable(path):
    try:
        os.listdir(path)
        return True
    except OSError:
        return False


def already_running(host, port):
    """True if another copy is serving the port. Windows lets two servers share a port
    (SO_REUSEADDR), which silently splits requests between them, so check first."""
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def serve(app, port=5000):
    host = os.environ.get('RECEIVING_CHECK_HOST', '192.168.60.215')
    if already_running(host, port):
        message = (f'Another copy of the app is already serving port {port}; not starting a second one. '
                   'To restart it correctly (desktop sign-in, with file-share access) run: '
                   'schtasks /run /tn "Receiving Log Web App (desktop)"')
        logging.error(message)
        print(message, file=sys.stderr)
        sys.exit(1)
    for share in app.config.get('REQUIRED_SHARES', []):
        if not share_reachable(share):
            logging.warning('Cannot open %s from this Windows sign-in; work-order PDFs will fail. '
                            'Start the app with: schtasks /run /tn "Receiving Log Web App (desktop)"', share)
    # Never create or migrate tables on startup; schema changes require approval.
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def main():
    logging.basicConfig(level=Config.LOG_LEVEL)
    serve(create_app())


if __name__ == '__main__':
    main()


