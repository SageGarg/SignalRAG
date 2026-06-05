"""
Entry point for the SignalRAG Flask application.
Run from the backend/ directory:

    python3 run.py

"""
import os
from dotenv import load_dotenv

load_dotenv()

from app.main import app

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_mode)
