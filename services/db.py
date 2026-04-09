import mysql.connector

# SignalVerse database connection
mydb = mysql.connector.connect(
  host="localhost",
  user="root",
  passwd="hello@123", # hello@123 for local and Working@2024
  database="Store"
)

mycursor = mydb.cursor()
mycursor.execute("CREATE DATABASE IF NOT EXISTS Store")
mycursor.execute("CREATE TABLE IF NOT EXISTS data (`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, SignalVerse_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)")

# BDIB
mydb_bdib = mysql.connector.connect(
  host="localhost",
  user="root",
  passwd="hello@123", # hello@123 for local and Working@2024
  database="Store_bdib"
)

mycursor_bdib = mydb_bdib.cursor()
mycursor_bdib.execute("CREATE DATABASE IF NOT EXISTS Store_bdib")
mycursor_bdib.execute("CREATE TABLE IF NOT EXISTS data (`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, BDIB_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)")

# NCHRP
mydb_nchrp = mysql.connector.connect(
    host="localhost",
    user="root",
    passwd="hello@123",  # hello@123 for local and Working@2024
    database="Store_nchrp"
)

mycursor_nchrp = mydb_nchrp.cursor()
mycursor_nchrp.execute("CREATE DATABASE IF NOT EXISTS Store_nchrp")
mycursor_nchrp.execute("CREATE TABLE IF NOT EXISTS data (`Sr. No.` INT, Email_ID VARCHAR(255), Question TEXT, nchrp_Answer TEXT, Rating INT, Raw_AI_Response TEXT, Rating2 INT)")

