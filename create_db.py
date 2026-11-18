"""Report model tables missing from the configured database.

Read-only by default. Creating tables requires explicit approval and BOTH:
    python create_db.py --create TABLE [TABLE ...] --confirm
Only the named missing tables are created; existing tables are never altered.
"""
import argparse

from sqlalchemy import inspect

from app import create_app
from models.models import db


def missing_tables():
    existing = set(inspect(db.engine).get_table_names())
    return sorted(name for name in db.metadata.tables if name not in existing)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--create', nargs='+', metavar='TABLE', help='Missing tables to create (approval required).')
    parser.add_argument('--confirm', action='store_true', help='Confirm table creation was approved.')
    args = parser.parse_args(argv)
    app = create_app()
    with app.app_context():
        missing = missing_tables()
        print('Missing model tables:', ', '.join(missing) if missing else 'none')
        if not args.create:
            print('No changes made (report only).')
            return 0
        unknown = sorted(set(args.create) - set(missing))
        if unknown:
            parser.error('Not missing model tables: ' + ', '.join(unknown) + '. Nothing created.')
        if not args.confirm:
            parser.error('Table creation requires approval; add --confirm. Nothing created.')
        tables = [db.metadata.tables[name] for name in args.create]
        db.metadata.create_all(db.engine, tables=tables, checkfirst=True)
        print('Created:', ', '.join(args.create))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
