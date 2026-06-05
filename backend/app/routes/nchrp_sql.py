"""
nchrp_sql.py — Text-to-SQL pipeline for NCHRP sensor testing Excel data.

Replaces the cosine-similarity approach in nchrp.py for Excel queries.
Drop-in replacement: call `build_db_from_files()` once at startup,
then use `ask_excel(question)` instead of `cosine_topk_keys()`.
"""

import os
import re
import json
import math
import sqlite3
import hashlib
import pandas as pd
import numpy as np
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CHAT_MODEL = "gpt-4o"

# ─────────────────────────────────────────────
# 1. SCHEMA
# ─────────────────────────────────────────────
#
# tests(test_id, vendor_name, sensor_model, sensor_technology,
#       stage_level, test_center, test_location, date_of_testing,
#       source_file, sheet_name)
#
# metrics(id, test_id, stage_level, sensor_function,
#         performance_measure, field_name, field_value, testing_notes)
#
# Canonical join: tests.test_id = metrics.test_id
#                 AND tests.stage_level = metrics.stage_level
#
# ─────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
DB_PATH = os.path.join(_PROJECT_ROOT, "nchrp.db")

SCHEMA_DESCRIPTION = """
Database: NCHRP sensor testing results.

TABLE: tests
  test_id          TEXT   – unique test identifier, e.g. 'CAL-016'
  vendor_name      TEXT   – manufacturer name
  sensor_model     TEXT   – model name of the sensor
  sensor_technology TEXT  – e.g. 'Inductive Loop', 'Video'
  stage_level      TEXT   – e.g. 'Stage 1 Level 1', 'Stage 2'
  test_center      TEXT   – name of test facility
  test_location    TEXT   – US state
  date_of_testing  TEXT   – ISO date string
  source_file      TEXT   – originating Excel filename
  sheet_name       TEXT   – Excel sheet name

TABLE: metrics
  id                   INTEGER PRIMARY KEY
  test_id              TEXT    – FK → tests.test_id
  stage_level          TEXT    – FK → tests.stage_level
  sensor_function      TEXT    – e.g. 'Detection', 'Classification'
  performance_measure  TEXT    – e.g. 'Detection Accuracy', 'Missed Calls'
  field_name           TEXT    – e.g. 'Measured value (%)', 'Sample size',
                                  '95% CI', 'Hypothesis test p-value',
                                  'Unit-to-unit variation', 'Weather', 'Lighting'
  field_value          TEXT    – the actual measured value or metadata
  testing_notes        TEXT    – optional notes flag ('Yes'/'No')

Join example:
  SELECT t.vendor_name, m.field_value
  FROM tests t JOIN metrics m
    ON t.test_id = m.test_id AND t.stage_level = m.stage_level
  WHERE m.performance_measure = 'Detection Accuracy'
    AND m.field_name = 'Measured value (%)';
"""

# ─────────────────────────────────────────────
# 2. NORMALISE + LOAD EXCEL → SQLITE
# ─────────────────────────────────────────────

def _norm_col(c: str) -> str:
    s = "" if c is None else str(c)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    key = s.lower()
    _CANON = {
        "test id": "Test ID",
        "vendor name": "Vendor Name",
        "sensor model name": "Sensor model name",
        "sensor technology": "Sensor Technology",
        "stage & level": "Stage & Level",
        "stage and level": "Stage & Level",
        "test center": "Test Center",
        "test location (state)": "Test Location (State)",
        "date of testing": "Date of Testing",
        "sensor function": "Sensor Function",
        "performance measure": "Performance Measure",
        "field name": "Field Name",
        "field value": "Field Value",
        "testing notes (optional)": "Testing Notes (optional)",
        "testing notes": "Testing Notes (optional)",
    }
    return _CANON.get(key, s)


def _norm_str(x) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x).replace("\u00a0", " ").strip()


def _json_safe(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return v.isoformat()
    if isinstance(v, str):
        s = v.replace("\u00a0", " ").strip()
        return s if s else None
    return v


def parse_excel_to_records(path: str):
    """
    Parse one .xlsx file (all sheets) into two lists:
      test_rows   – one dict per (test_id, stage_level)
      metric_rows – one dict per field_name/field_value entry
    """
    test_rows, metric_rows = [], []
    xls = pd.ExcelFile(path, engine="openpyxl")
    source_file = os.path.basename(path)

    for sheet in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sheet, dtype=object)
        df.columns = [_norm_col(c) for c in df.columns]
        # Drop unnamed columns
        df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
        df = df.where(pd.notnull(df), None)

        # Strip strings
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

        df = df.dropna(how="all")
        if df.empty:
            continue

        # Forward-fill sparse columns (merged-cell style)
        for col in ["Test ID", "Sensor Function", "Performance Measure", "Stage & Level"]:
            if col in df.columns:
                df[col] = df[col].replace("", None).ffill()

        required = {"Test ID", "Stage & Level", "Field Name", "Field Value"}
        if not required.issubset(df.columns):
            continue

        df = df[df["Test ID"].notna() & df["Stage & Level"].notna()]
        if df.empty:
            continue

        SUMMARY_COLS = [
            "Test ID", "Vendor Name", "Sensor model name", "Sensor Technology",
            "Stage & Level", "Test Center", "Test Location (State)", "Date of Testing",
        ]

        # Emit one test row per unique (test_id, stage_level)
        for _, row in df[SUMMARY_COLS].drop_duplicates(
            subset=["Test ID", "Stage & Level"]
        ).iterrows():
            test_rows.append({
                "test_id":           _norm_str(row.get("Test ID")),
                "vendor_name":       _norm_str(row.get("Vendor Name")),
                "sensor_model":      _norm_str(row.get("Sensor model name")),
                "sensor_technology": _norm_str(row.get("Sensor Technology")),
                "stage_level":       _norm_str(row.get("Stage & Level")),
                "test_center":       _norm_str(row.get("Test Center")),
                "test_location":     _norm_str(row.get("Test Location (State)")),
                "date_of_testing":   _norm_str(_json_safe(row.get("Date of Testing"))),
                "source_file":       source_file,
                "sheet_name":        sheet,
            })

        # Emit one metric row per (test_id, stage_level, sensor_function, perf_measure, field_name)
        for _, row in df.iterrows():
            fn = _norm_str(row.get("Field Name"))
            fv = _norm_str(row.get("Field Value"))
            if not fn or not fv:
                continue
            metric_rows.append({
                "test_id":             _norm_str(row.get("Test ID")),
                "stage_level":         _norm_str(row.get("Stage & Level")),
                "sensor_function":     _norm_str(row.get("Sensor Function")),
                "performance_measure": _norm_str(row.get("Performance Measure")),
                "field_name":          fn,
                "field_value":         fv,
                "testing_notes":       _norm_str(row.get("Testing Notes (optional)")),
            })

    return test_rows, metric_rows


def build_db_from_files(data_dirs: list[str], db_path: str = DB_PATH):
    """
    Scan all .xlsx and .csv files in data_dirs, parse them,
    and upsert into a local SQLite database.
    Returns the db_path.
    """
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS tests (
            test_id           TEXT,
            vendor_name       TEXT,
            sensor_model      TEXT,
            sensor_technology TEXT,
            stage_level       TEXT,
            test_center       TEXT,
            test_location     TEXT,
            date_of_testing   TEXT,
            source_file       TEXT,
            sheet_name        TEXT,
            PRIMARY KEY (test_id, stage_level)
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id              TEXT,
            stage_level          TEXT,
            sensor_function      TEXT,
            performance_measure  TEXT,
            field_name           TEXT,
            field_value          TEXT,
            testing_notes        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_test    ON metrics(test_id);
        CREATE INDEX IF NOT EXISTS idx_metrics_pm      ON metrics(performance_measure);
        CREATE INDEX IF NOT EXISTS idx_metrics_fn      ON metrics(field_name);
        CREATE INDEX IF NOT EXISTS idx_metrics_sf      ON metrics(sensor_function);
    """)

    for data_dir in data_dirs:
        if not os.path.isdir(data_dir):
            continue
        for fname in os.listdir(data_dir):
            if fname.startswith(("~$", ".")):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".xlsx", ".csv"):
                continue
            fpath = os.path.join(data_dir, fname)
            try:
                tests, metrics = parse_excel_to_records(fpath)
                cur.executemany(
                    """INSERT OR REPLACE INTO tests VALUES
                       (:test_id,:vendor_name,:sensor_model,:sensor_technology,
                        :stage_level,:test_center,:test_location,:date_of_testing,
                        :source_file,:sheet_name)""",
                    tests,
                )
                # Delete old metrics for these (test_id, stage_level) combos, then re-insert
                keys = list({(t["test_id"], t["stage_level"]) for t in tests})
                cur.executemany(
                    "DELETE FROM metrics WHERE test_id=? AND stage_level=?", keys
                )
                cur.executemany(
                    """INSERT INTO metrics
                       (test_id,stage_level,sensor_function,performance_measure,
                        field_name,field_value,testing_notes)
                       VALUES
                       (:test_id,:stage_level,:sensor_function,:performance_measure,
                        :field_name,:field_value,:testing_notes)""",
                    metrics,
                )
            except Exception as e:
                print(f"[WARN] Skipping {fname}: {e}")

    con.commit()
    con.close()
    return db_path


# ─────────────────────────────────────────────
# 3. TEXT-TO-SQL QUERY ENGINE
# ─────────────────────────────────────────────

_SQL_FENCE = re.compile(r"```(?:sql)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _get_known_values(db_path: str = DB_PATH) -> dict:
    """
    Pull distinct categorical values from the live DB so the LLM
    can use exact strings in WHERE clauses instead of guessing.
    Returns an empty dict safely if the DB doesn't exist yet.
    """
    result = {
        "field_name": [],
        "performance_measure": [],
        "sensor_function": [],
        "sensor_technology": [],
    }
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        for col, tbl in [
            ("field_name",           "metrics"),
            ("performance_measure",  "metrics"),
            ("sensor_function",      "metrics"),
            ("sensor_technology",    "tests"),
        ]:
            cur.execute(
                f"SELECT DISTINCT {col} FROM {tbl} WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col} LIMIT 60"
            )
            result[col] = [r[0] for r in cur.fetchall()]
        con.close()
    except Exception as e:
        print(f"[_get_known_values] Could not read DB: {e}")
    return result

def _extract_sql(text: str) -> str:
    m = _SQL_FENCE.search(text)
    if m:
        return m.group(1).strip()
    # Fall back: return everything after a SELECT keyword
    upper = text.upper()
    idx = upper.find("SELECT")
    if idx != -1:
        return text[idx:].strip()
    return text.strip()


def _generate_sql(question: str, error_feedback: str = "", db_path: str = DB_PATH) -> str:
    """Ask GPT to write a SQL query for the question."""
    feedback_block = (
        f"\nPrevious attempt failed with error: {error_feedback}\nPlease fix the SQL.\n"
        if error_feedback else ""
    )

    # Pull real values from the DB so GPT uses exact strings, not guesses
    known = _get_known_values(db_path)
    known_block = ""
    if any(known.values()):
        known_block = f"""
⚠️  IMPORTANT — Use ONLY these exact strings in WHERE clauses (they are case-sensitive):
  field_name values          : {known['field_name']}
  performance_measure values : {known['performance_measure']}
  sensor_function values     : {known['sensor_function']}
  sensor_technology values   : {known['sensor_technology']}

Never invent or substitute values not in these lists.
If the user's term does not match any known value, omit that filter entirely and let the keyword pre-check handle relevance.
"""

    prompt = f"""
You are a SQL expert. Given the database schema below, write a single SQLite SELECT query
to answer the user's question. Return ONLY the SQL inside a ```sql ... ``` code block.
Do not explain. Do not add comments inside the SQL.

RULE: Always include t.source_file as the LAST column in your SELECT so users can download the source data.
      Even for DISTINCT or aggregate queries, append t.source_file (or source_file if unambiguous).

{SCHEMA_DESCRIPTION}
{known_block}
{feedback_block}
User question: {question}
""".strip()

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return _extract_sql(resp.choices[0].message.content)


def _run_sql(sql: str, db_path: str = DB_PATH):
    """Execute SQL and return (columns, rows) or raise."""
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    con.close()
    return cols, rows


def _synthesise_answer(question: str, sql: str, cols: list, rows: list) -> str:
    """Ask GPT to turn SQL results into a plain-English answer."""
    if not rows:
        table_str = "No rows returned."
    else:
        header = " | ".join(cols)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows[:50])
        table_str = f"{header}\n{body}"
        if len(rows) > 50:
            table_str += f"\n... ({len(rows) - 50} more rows)"

    prompt = f"""
You are answering a question about NCHRP sensor testing data.

User question: {question}

SQL used:
{sql}

Query result:
{table_str}

Write a concise, clear answer using ONLY the data above.
If the result is empty, say "No matching data found."
""".strip()

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )
    return resp.choices[0].message.content.strip()


_STOP_WORDS = {
    'the','a','an','is','are','was','were','be','been','have','has','had',
    'do','does','did','will','would','could','should','may','can','for',
    'and','or','but','in','on','at','to','from','by','with','of','that',
    'this','what','who','how','when','where','show','list','give','get',
    'find','tell','me','all','any','some','not','no','there','much','more',
    'many','few','each','every','about','which','please','using','used',
}

_SEARCH_COLS = [
    't.test_id', 't.vendor_name', 't.sensor_model', 't.sensor_technology',
    't.test_center', 't.test_location',
    'm.sensor_function', 'm.performance_measure', 'm.field_name', 'm.field_value',
]

def _keyword_match(question: str, db_path: str = DB_PATH) -> bool:
    """
    Returns True if any meaningful word from the question appears as a substring
    in any text column of the database. Fails open (returns True) on error.
    """
    words = [
        w.lower().strip(".,!?;:\"'()-")
        for w in question.split()
        if len(w) > 2 and w.lower().strip(".,!?;:\"'()-") not in _STOP_WORDS
    ]
    if not words:
        return False

    conditions = []
    for word in words:
        safe = word.replace("'", "''")
        for col in _SEARCH_COLS:
            conditions.append(f"LOWER({col}) LIKE '%{safe}%'")

    sql = (
        "SELECT 1 FROM tests t "
        "LEFT JOIN metrics m ON t.test_id = m.test_id AND t.stage_level = m.stage_level "
        f"WHERE {' OR '.join(conditions)} LIMIT 1"
    )
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute(sql)
        found = cur.fetchone() is not None
        con.close()
        print(f"[keyword_match] words={words} found={found}")
        return found
    except Exception as e:
        print(f"[keyword_match] error: {e}")
        return True  # fail open


def ask_excel(question: str, db_path: str = DB_PATH, max_retries: int = 2) -> dict:
    """
    Main entry point. Returns:
      {
        "answer": str,
        "sql": str,
        "columns": [...],
        "rows": [[...], ...],
        "error": str | None
      }
    """
    # Pre-check: search the database for question keywords before calling GPT
    if not _keyword_match(question, db_path):
        return {
            "answer": "No matching data found in the sensor testing database for this query.",
            "sql": "",
            "columns": [],
            "rows": [],
            "error": None,
        }

    sql = ""
    error = None
    for attempt in range(max_retries + 1):
        try:
            sql = _generate_sql(question, error_feedback=error or "", db_path=db_path)
            cols, rows = _run_sql(sql, db_path)
            answer = _synthesise_answer(question, sql, cols, rows)
            return {
                "answer": answer,
                "sql": sql,
                "columns": cols,
                "rows": [list(r) for r in rows],
                "error": None,
            }
        except Exception as e:
            error = str(e)
            print(f"[SQL attempt {attempt + 1}] Error: {error}\nSQL: {sql}")

    return {
        "answer": "I could not retrieve the answer from the database.",
        "sql": sql,
        "columns": [],
        "rows": [],
        "error": error,
    }


# ─────────────────────────────────────────────
# ─────────────────────────────────────────────
# 4. UNIFIED ROUTER  (Excel SQL  +  PDF RAG — parallel)
# ─────────────────────────────────────────────

_PDF_NO_ANSWER_PHRASES = (
    "not explicitly mentioned",
    "not mentioned in",
    "not discussed",
    "i don't have sufficient",
    "don't have information",
    "further research",
    "cannot answer",
    "no information",
    "not covered",
    "not addressed",
    "pdf source unavailable",
    "i don't know based on",
)

def _pdf_has_no_answer(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in _PDF_NO_ANSWER_PHRASES)


def route_and_answer(question: str, pdf_answer_fn=None, db_path: str = DB_PATH) -> dict:
    """
    Runs Excel SQL and PDF RAG in parallel — no LLM router needed.
    Decision is purely data-driven: whichever source has real results wins.
    Returns {answer, route, sql, rows, columns, off_topic}
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        excel_future = executor.submit(ask_excel, question, db_path)
        pdf_future   = executor.submit(pdf_answer_fn, question) if pdf_answer_fn else None

        excel_result = excel_future.result()
        pdf_result   = pdf_future.result() if pdf_future else ""

    print(f"[router] excel_rows={len(excel_result.get('rows', []))} pdf_no_answer={_pdf_has_no_answer(pdf_result or '')}")

    # Excel has rows → use it
    if excel_result.get("rows"):
        return {**excel_result, "route": "EXCEL", "off_topic": False}

    # PDF has a meaningful answer → use it
    if pdf_result and not _pdf_has_no_answer(pdf_result):
        return {
            "answer":   pdf_result,
            "route":    "PDF",
            "sql":      excel_result.get("sql", ""),
            "rows":     [],
            "columns":  [],
            "off_topic": False,
        }

    # Neither answered → off-topic
    return {
        "answer":   "",
        "route":    "NONE",
        "sql":      excel_result.get("sql", ""),
        "rows":     [],
        "columns":  [],
        "off_topic": True,
    }


# ─────────────────────────────────────────────
# 5.  QUICK TEST / DEMO
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    SAMPLE_DIR = "sampleData"   # ← change to your actual data folder
    print("Building SQLite DB …")
    build_db_from_files([SAMPLE_DIR])

    test_questions = [
        "What is the detection accuracy for CAL-016 at Stage 1 Level 1?",
        "Which vendor has the highest detection accuracy?",
        "Show all sensors tested in Florida.",
        "What is the missed call rate for Inductive Loop sensors at Stage 2?",
        "How many unique test IDs are in the dataset?",
    ]

    for q in test_questions:
        print(f"\n{'='*60}\nQ: {q}")
        result = ask_excel(q)
        print(f"SQL:\n{result['sql']}")
        print(f"Answer:\n{result['answer']}")
