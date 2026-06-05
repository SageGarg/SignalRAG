import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "hello@123") #Working@2024 for deployed version

# ── SignalVerse ───────────────────────────────────────────────────────────────
mydb = mysql.connector.connect(
    host=DB_HOST,
    user=DB_USER,
    passwd=DB_PASSWORD,
    database=os.getenv("DB_NAME_SIGNALVERSE", "Store")
)
mycursor = mydb.cursor()
mycursor.execute("CREATE DATABASE IF NOT EXISTS Store")
mycursor.execute(
    "CREATE TABLE IF NOT EXISTS data ("
    "`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, "
    "SignalVerse_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)"
)

# ── BDIB ─────────────────────────────────────────────────────────────────────
mydb_bdib = mysql.connector.connect(
    host=DB_HOST,
    user=DB_USER,
    passwd=DB_PASSWORD,
    database=os.getenv("DB_NAME_BDIB", "Store_bdib")
)
mycursor_bdib = mydb_bdib.cursor()
mycursor_bdib.execute("CREATE DATABASE IF NOT EXISTS Store_bdib")
mycursor_bdib.execute(
    "CREATE TABLE IF NOT EXISTS data ("
    "`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, "
    "BDIB_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)"
)

# ── NCHRP ─────────────────────────────────────────────────────────────────────
mydb_nchrp = mysql.connector.connect(
    host=DB_HOST,
    user=DB_USER,
    passwd=DB_PASSWORD,
    database=os.getenv("DB_NAME_NCHRP", "Store_nchrp")
)
mycursor_nchrp = mydb_nchrp.cursor()
mycursor_nchrp.execute("CREATE DATABASE IF NOT EXISTS Store_nchrp")
mycursor_nchrp.execute(
    "CREATE TABLE IF NOT EXISTS data ("
    "`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, "
    "nchrp_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)"
)
