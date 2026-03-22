import logging

from flask import Flask
from flask_jwt_extended import JWTManager
from flask_sqlalchemy import SQLAlchemy

from config import config_map

logger = logging.getLogger(__name__)
db = SQLAlchemy()
jwt = JWTManager()


def _migrate_add_timezone_column(db) -> None:
    """Add the `timezone` column to the timer table if it doesn't exist (one-time migration)."""
    try:
        with db.engine.connect() as conn:
            result = conn.execute(db.text("PRAGMA table_info(timer)"))
            columns = {row[1] for row in result}
            if "timezone" not in columns:
                conn.execute(db.text("ALTER TABLE timer ADD COLUMN timezone VARCHAR(50) DEFAULT 'UTC'"))
                conn.commit()
                logger.info("Migrated: added 'timezone' column to timer table")
    except Exception as e:
        logger.warning("Could not run timezone migration: %s", e)


def create_app(config_name: str = "default") -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_map[config_name])

    db.init_app(app)
    jwt.init_app(app)

    # Register blueprints
    from .auth import auth_bp
    from .timers import timers_bp
    from .web import web_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(timers_bp, url_prefix="/api/timers")
    app.register_blueprint(web_bp)

    with app.app_context():
        db.create_all()
        _migrate_add_timezone_column(db)

        if app.config.get("SCHEDULER_ENABLED", True):
            from . import scheduler_service
            scheduler_service.init_scheduler(app)
            scheduler_service.restore_timers(app)

    return app
