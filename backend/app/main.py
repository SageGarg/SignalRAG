import os
from flask import Flask
from dotenv import load_dotenv

# Load environment variables from .env before anything else
load_dotenv()

from .services.llm import init_vectorstores, answer_question, check_relevance, client
from .services.db import mycursor_nchrp, mydb_nchrp

from .routes.bdib import create_bdib_blueprint
from .routes.signalverse import create_signalverse_blueprint
from .routes.nchrp import create_nchrp_blueprint
from .routes.nchrp_sql import build_db_from_files

# Resolve folders from this file's absolute location
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

app = Flask(
    __name__,
    root_path=_ROOT,                                            # fixes current_app.root_path → project root
    template_folder=os.path.join(_ROOT, "frontend", "src", "pages"),
    static_folder=os.path.join(_ROOT, "frontend", "src", "assets"),
    static_url_path="/static",                                  # keeps url_for('static',...) → /static/
)

# Secret key loaded from env — never hard-coded
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-in-production")

# Hardcoded fallback — used if ALLOWED_EMAILS is not set in .env
_DEFAULT_EMAILS = {
    "sg1807@iastate.edu",
    "aparnaj8@iastate.edu",
    "anujs@iastate.edu",
    "kevin.balke@gmail.com",
    "s-sunkari@tti.tamu.edu",
    "a-bibeka@tti.tamu.edu",
    "s-poddar@tti.tamu.edu"
}
_env_emails = {
    e.strip() for e in os.getenv("ALLOWED_EMAILS", "").split(",") if e.strip()
}
ALLOWED_EMAILS = _env_emails if _env_emails else _DEFAULT_EMAILS

mail_config = {
    "server":   os.getenv("MAIL_SERVER",   "smtp.gmail.com"),
    "port":     int(os.getenv("MAIL_PORT", "587")),
    "username": os.getenv("MAIL_USERNAME", ""),
    "password": os.getenv("MAIL_PASSWORD", ""),
}

# Initialize vectorstores on startup
vectorstores = init_vectorstores()

# Build SQLite DB from sampleData + uploaded Excel files
build_db_from_files([
    os.path.join(_ROOT, "sampleData"),
    os.path.join(_ROOT, "uploads", "excel"),
])

# Create blueprints
bdib_bp = create_bdib_blueprint(vectorstores=vectorstores)
signalverse_bp = create_signalverse_blueprint(vectorstores=vectorstores)
nchrp_bp = create_nchrp_blueprint(
    vectorstores=vectorstores,
    answer_question=answer_question,
    check_relevance=check_relevance,
    client=client,
    allowed_emails=ALLOWED_EMAILS,
    mycursor_nchrp=mycursor_nchrp,
    mydb_nchrp=mydb_nchrp,
    mail_config=mail_config,
)

# Register blueprints
app.register_blueprint(signalverse_bp)
app.register_blueprint(bdib_bp, url_prefix='/bdib_bp')
app.register_blueprint(nchrp_bp, url_prefix="/nchrp_bp")