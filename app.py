from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import text
from tempfile import NamedTemporaryFile
import logging
import os
import re
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

def create_app():
    """Application factory — makes testing & deployment easier."""
    app = Flask(__name__,
                template_folder="templates",
                static_folder="static")
    app.config.from_object(Config)

    # initialize SQLAlchemy
    db.init_app(app)

    # register modular routes
    app.register_blueprint(index_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route('/api/word-files', methods=['GET'])
    def get_word_files():
        try:
            rows = db.session.execute(
                text("SELECT * FROM word_file_log")
            ).mappings().all()
            word_files_data = [
                {
                    "file_name": row.get("file_name"),
                    "order_id": row.get("order_id"),
                    "status": "Picked" if row.get("product_details") else "No",
                    "file_path": row.get("file_path")
                }
                for row in rows
            ]
            return jsonify({"word_files": word_files_data}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app

if __name__ == '__main__':
    logging.basicConfig(level=Config.LOG_LEVEL)
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)


