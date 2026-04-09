from flask import Flask
import os

from services.llm import init_vectorstores, answer_question, client
from services.db import mycursor_nchrp, mydb_nchrp

from blueprints.bdib import create_bdib_blueprint
from blueprints.signalverse import create_signalverse_blueprint
from blueprints.nchrp import create_nchrp_blueprint

app = Flask(__name__)
app.secret_key = "abcd"
chat_history = []

ALLOWED_EMAILS = {
    "sg1807@iastate.edu",
    "aparnaj8@iastate.edu",
    "anujs@iastate.edu",
    "kevin.balke@gmail.com",
    "s-sunkari@tti.tamu.edu",
    "a-bibeka@tti.tamu.edu",
    "s-poddar@tti.tamu.edu"
}

# Initialize vectorstores on startup
print("Initializing Vectorstores...")
vectorstores = init_vectorstores()
print("Vectorstores Initialized.")

# Create blueprints
bdib_bp = create_bdib_blueprint(vectorstores=vectorstores, chat_history=chat_history)
signalverse_bp = create_signalverse_blueprint(vectorstores=vectorstores, chat_history=chat_history)
nchrp_bp = create_nchrp_blueprint(
    vectorstores=vectorstores,
    answer_question=answer_question,
    client=client,
    allowed_emails=ALLOWED_EMAILS,
    mycursor_nchrp=mycursor_nchrp,
    mydb_nchrp=mydb_nchrp,
    chat_history=chat_history
)

# Register blueprints
# SignalVerse is the main index for now, so no prefix. Or we register it at root.
app.register_blueprint(signalverse_bp)
app.register_blueprint(bdib_bp, url_prefix='/bdib_bp')
app.register_blueprint(nchrp_bp, url_prefix="/nchrp_bp")

if __name__ == '__main__':
    app.run(debug=True)
