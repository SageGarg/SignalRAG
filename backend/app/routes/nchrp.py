from flask import (
    Blueprint, render_template, request, session, jsonify,
    redirect, url_for, flash, current_app, send_from_directory, send_file
)
from typing import List, Dict, Tuple, Any 
import os, re, json, math, io, zipfile, secrets, smtplib
import pandas as pd
from werkzeug.utils import secure_filename
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from .nchrp_sql import ask_excel, build_db_from_files, route_and_answer
import numpy as np
#below lists are used by upload report 
ALLOWED_REPORT_EXT = {".xlsx", ".csv"}

ALLOWED_META_EXT = {
    ".pdf", ".doc", ".docx", ".txt",
    ".png", ".jpg", ".jpeg", ".webp",
    ".csv", ".xlsx"
}

_histories: dict = {}

def _sid() -> str:
    if "_nchrp_sid" not in session:
        session["_nchrp_sid"] = secrets.token_hex(8)
    return session["_nchrp_sid"]

def _get_history() -> list:
    return _histories.setdefault(_sid(), [])

def _clear_nchrp_history():
    _histories[_sid()] = []

def create_nchrp_blueprint(*, vectorstores, answer_question, check_relevance, client, allowed_emails, mycursor_nchrp, mydb_nchrp, mail_config):
    nchrp_bp = Blueprint("nchrp_bp", __name__)

    def _send_otp_email(to_email: str, otp: str) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Your NCHRP Clearinghouse Access Code"
            msg["From"] = mail_config["username"]
            msg["To"] = to_email
            body = (
                f"Your verification code is: {otp}\n\n"
                "This code expires in 5 minutes.\n\n"
                "If you did not request this, please ignore this email."
            )
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(mail_config["server"], mail_config["port"]) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(mail_config["username"], mail_config["password"])
                smtp.sendmail(mail_config["username"], to_email, msg.as_string())
            return True
        except Exception as e:
            print(f"[OTP] Email send failed: {e}")
            return False

    def _mask_email(email: str) -> str:
        if "@" not in email:
            return email
        local, domain = email.split("@", 1)
        return local[:2] + "***@" + domain

    def _clear_pending(sess):
        for k in ("pending_otp", "pending_otp_expires", "pending_email", "pending_name", "pending_role"):
            sess.pop(k, None)

    # ----------------------------
    # used by load_nchrp_from_files()
    # ----------------------------
    # same for entire sheet
    SUMMARY_COLS = [
        "Test ID",
        "Vendor Name",
        "Sensor model name",
        "Sensor Technology",
        "Stage & Level",
        "Test Center",
        "Test Location (State)",
        "Date of Testing",
        # "Ground Truth Source",
    ]

    # NEW (long-format metrics)
    METRIC_BASE_COLS = [
        "Test ID",
        "Sensor Function",
        "Performance Measure",
        "Field Name",
        "Field Value",
    ]


    OPTIONAL_METRIC_COLS = ["Testing Notes (optional)"]

    def norm_str(x) -> str:
        if x is None:
            return ""
        try:
            if pd.isna(x):
                return ""
        except Exception:
            pass
        return str(x).strip()

    # if the excel file has some inconsistences in column naming
    def _norm_col(c) -> str:
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
            # "ground truth source": "Ground Truth Source",
            "sensor function": "Sensor Function",
            "performance measure": "Performance Measure",
            "measured value (%)": "Measured value (%)",
            "measured value %": "Measured value (%)",
            "sample size": "Sample size",
            "weather (f)": "Weather (F)",
            "lighting": "Lighting",
            "testing notes (optional)": "Testing Notes (optional)",
            "testing notes": "Testing Notes (optional)",
            "field name": "Field Name",
            "field value": "Field Value",
            "field_value": "Field Value",
            "field_name": "Field Name",
        }
        return _CANON.get(key, s)

    def json_safe(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        if isinstance(v, (np.generic,)):
            return json_safe(v.item())
        if isinstance(v, (datetime, date, pd.Timestamp)):
            return v.isoformat()
        if isinstance(v, str):
            s = v.replace("\u00a0", " ").strip()
            return s if s != "" else None
        return v

    def load_nchrp_from_files(also_rebuild_db: bool = False):
        sample_dir = os.path.join(current_app.root_path, "sampleData")
        upload_excel_dir = os.path.join(current_app.root_path, "uploads", "excel")
        if also_rebuild_db:
            build_db_from_files([sample_dir, upload_excel_dir])
        frames = []
        
        directories_to_scan = [sample_dir, upload_excel_dir]
        
        for data_dir in directories_to_scan:
            if not os.path.isdir(data_dir):
                continue

            for fn in os.listdir(data_dir):
                if fn.startswith("~$") or fn.startswith("."):
                    continue
                path = os.path.join(data_dir, fn)
                if not os.path.isfile(path):
                    continue
                ext = os.path.splitext(fn)[1].lower()

                try:
                    if ext == ".csv":
                        df = pd.read_csv(path, dtype=object)
                        df.columns = [_norm_col(c) for c in df.columns]
                        df["__source__"] = fn
                        df["__sheet__"] = None
                        frames.append(df)

                    elif ext == ".xlsx":
                        xls = pd.ExcelFile(path, engine="openpyxl")
                        for sheet in xls.sheet_names:
                            s = pd.read_excel(xls, sheet_name=sheet, dtype=object)
                            s.columns = [_norm_col(c) for c in s.columns]
                            s = s.loc[:, ~s.columns.astype(str).str.startswith("Unnamed")]
                            s = s.where(pd.notnull(s), None)

                            for c in s.columns:
                                if s[c].dtype == object:
                                    s[c] = s[c].apply(lambda x: x.strip() if isinstance(x, str) else x)

                            s = s.dropna(how="all")
                            if s.empty:
                                continue

                            for col in ["Test ID", "Sensor Function","Performance Measure", "Stage & Level"]:
                                if col in s.columns:
                                    s[col] = s[col].replace("", None).ffill()

                            if "Stage & Level" not in s.columns or s["Stage & Level"].isna().all():
                                continue
                            if "Test ID" not in s.columns or s["Test ID"].isna().all():
                                continue

                            s["__source__"] = fn
                            s["__sheet__"] = sheet
                            frames.append(s)

                except Exception as e:
                    print(f"[WARN] Skipping file {fn}: {e}")
                    continue

        if not frames:
            return [], {}

        df = pd.concat(frames, ignore_index=True)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
        df = df.where(pd.notnull(df), None)

        for c in df.columns:
            if df[c].dtype == object:
                df[c] = df[c].apply(lambda x: x.strip() if isinstance(x, str) else x)

        required = set(SUMMARY_COLS + METRIC_BASE_COLS)
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError("Missing required columns: " + ", ".join(missing))

        df["Test ID"] = df["Test ID"].replace("", None)
        df["Stage & Level"] = df["Stage & Level"].replace("", None)
        df = df[df["Test ID"].notna() & df["Stage & Level"].notna()]
        df = df[(df["Test ID"].astype(str).str.strip() != "") & (df["Stage & Level"].astype(str).str.strip() != "")]
        if df.empty:
            return [], {}

        df["__key__"] = df["Test ID"].astype(str).str.strip() + "||" + df["Stage & Level"].astype(str).str.strip()

        tests_df = df[SUMMARY_COLS + ["__key__"]].drop_duplicates(subset=["__key__"]).copy()
        tests = []
        for _, r in tests_df.iterrows():
            rec = {k: json_safe(r.get(k)) for k in (SUMMARY_COLS + ["__key__"])}
            for k, v in list(rec.items()):
                if v is None:
                    rec[k] = ""
            tests.append(rec)

        metric_cols = [c for c in (METRIC_BASE_COLS + OPTIONAL_METRIC_COLS) if c in df.columns]
        for extra in ["__source__", "__sheet__"]:
            if extra in df.columns and extra not in metric_cols:
                metric_cols.append(extra)

        # ✅ Build metrics_by_key ONCE
        metrics_by_key = {}

        group_cols = ["__key__", "Sensor Function", "Performance Measure"]
        keep_cols = [
            "__key__", "Sensor Function", "Performance Measure",
            "Field Name", "Field Value", "__source__", "__sheet__",
            "Testing Notes (optional)"
        ]
        keep_cols = [c for c in keep_cols if c in df.columns]

        work = df[keep_cols].copy()

        # drop rows where KV pair is missing
        work["Field Name"] = work["Field Name"].apply(norm_str)
        work["Field Value"] = work["Field Value"].apply(norm_str)
        work = work[(work["Field Name"] != "") & (work["Field Value"] != "")]

        for (k, sf, pm), g in work.groupby(group_cols, dropna=False):
            k  = norm_str(k)
            sf = norm_str(sf) or "Unknown"
            pm = norm_str(pm) or "Unknown"

            fields = {}
            for _, r in g.iterrows():
                fname = norm_str(r.get("Field Name"))
                fval  = json_safe(r.get("Field Value"))
                if fname:
                    fields[fname] = fval  # last wins

            notes = ""
            if "Testing Notes (optional)" in g.columns:
                notes_s = g["Testing Notes (optional)"].dropna()
                if not notes_s.empty:
                    notes = notes_s.iloc[0]

            metrics_by_key.setdefault(k, []).append({
                "Sensor Function": sf,
                "Performance Measure": pm,
                "fields": fields,
                "ordered_fields": list(fields.keys()),
                "Testing Notes": norm_str(notes),
                "__source__": g.iloc[0].get("__source__"),
                "__sheet__": g.iloc[0].get("__sheet__"),
            })

        return tests, metrics_by_key



    @nchrp_bp.route("/")
    def index_nchrp():
        _clear_nchrp_history()
        return render_template("index_nchrp.html")

    @nchrp_bp.route("/clear_chat_history", methods=["POST"])
    def clear_chat_history_nchrp():
        _clear_nchrp_history()
        return redirect(url_for("nchrp_bp.go_to_clearinghouse"))

    @nchrp_bp.route("/answer_nchrp", methods=["POST"])
    def answer_nchrp():
        user_name = request.form["user_question"]
        user_email = request.form["user_email"].strip().lower()
        user_role = request.form.get("user_role", "").strip().lower()

        if user_email not in allowed_emails:
            flash("Your access is not approved yet.")
            return render_template("index_nchrp.html")

        otp = f"{secrets.randbelow(1000000):06d}"
        session["pending_otp"] = otp
        session["pending_otp_expires"] = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        session["pending_email"] = user_email
        session["pending_name"] = user_name
        session["pending_role"] = user_role

        print(f"[DEV] OTP for {user_email}: {otp}")
        if not _send_otp_email(user_email, otp):
            flash("Failed to send verification email. Please try again.")
            return render_template("index_nchrp.html")

        return redirect(url_for("nchrp_bp.verify_otp"))

    @nchrp_bp.route("/verify_otp", methods=["GET", "POST"])
    def verify_otp():
        if "pending_email" not in session:
            flash("Please log in first.")
            return redirect(url_for("nchrp_bp.index_nchrp"))

        if request.method == "GET":
            return render_template("verify_otp.html", masked_email=_mask_email(session["pending_email"]))

        entered = request.form.get("otp_code", "").strip()
        stored_otp = session.get("pending_otp", "")
        expires_str = session.get("pending_otp_expires", "")

        try:
            expires = datetime.fromisoformat(expires_str)
        except Exception:
            flash("Session expired. Please log in again.")
            _clear_pending(session)
            return redirect(url_for("nchrp_bp.index_nchrp"))

        if datetime.utcnow() > expires:
            flash("Code expired. Please log in again.")
            _clear_pending(session)
            return redirect(url_for("nchrp_bp.index_nchrp"))

        if not secrets.compare_digest(entered, stored_otp):
            flash("Incorrect code. Please try again.")
            return render_template("verify_otp.html", masked_email=_mask_email(session["pending_email"]))

        session["user_email"] = session.pop("pending_email")
        session["user_name"] = session.pop("pending_name")
        session["user_role"] = session.pop("pending_role")
        session.pop("pending_otp", None)
        session.pop("pending_otp_expires", None)
        _clear_nchrp_history()
        return redirect(url_for("nchrp_bp.choices"))

    @nchrp_bp.route("/resend_otp", methods=["POST"])
    def resend_otp():
        if "pending_email" not in session:
            return redirect(url_for("nchrp_bp.index_nchrp"))

        otp = f"{secrets.randbelow(1000000):06d}"
        session["pending_otp"] = otp
        session["pending_otp_expires"] = (datetime.utcnow() + timedelta(minutes=5)).isoformat()

        if not _send_otp_email(session["pending_email"], otp):
            flash("Failed to resend code. Please try again.")
        else:
            flash("A new code has been sent to your email.")
        return redirect(url_for("nchrp_bp.verify_otp"))

    @nchrp_bp.route("/choices", methods=["GET"])
    def choices():
        if "user_email" not in session:
            flash("Please log in first.")
            return redirect(url_for("nchrp_bp.index_nchrp"))
        return render_template(
            "nchrp_choice.html", 
            user_name=session.get("user_name", ""), 
            user_email=session.get("user_email", ""), 
            user_role=session.get("user_role", "")
        )

    @nchrp_bp.route("/go_to_clearinghouse", methods=["GET"])
    def go_to_clearinghouse():
        if "user_email" not in session:
            flash("Please log in first.")
            return redirect(url_for("nchrp_bp.index_nchrp"))
        return render_template("answer_nchrp.html", user_name=session.get("user_name", ""))

    @nchrp_bp.route("/submit_question_nchrp", methods=["POST"])
    def submit_question_nchrp():
        ques_input = request.form["quesInput"]
        if ques_input:
            session["question"] = ques_input
            return redirect(url_for("nchrp_bp.display_result_nchrp", user_name=session.get("user_name", "")))
        return redirect(url_for("nchrp_bp.index_nchrp"))

    @nchrp_bp.route("/result/<user_name>")
    def display_result_nchrp(user_name):
        ques_input = session["question"]
        vectorstore = vectorstores["nchrp"]

        answer, sources = answer_question(ques_input, vectorstore)

        # Data-driven guardrail: no relevant docs found → off-topic popup
        _NO_ANSWER = "i don't have sufficient information in the available documents"
        if answer.lower().startswith(_NO_ANSWER):
            return render_template(
                "answer_nchrp.html",
                user_name=session.get("user_name", ""),
                chat_history=_get_history(),
                off_topic=True,
            )

        prompt = f"In context of transportation answer this: {ques_input}"
        ChipAnswerText = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        ChipAnswer = ChipAnswerText.choices[0].message.content.strip()

        session["answer"] = answer
        session["ChipAnswer"] = ChipAnswer

        _get_history().append({"question": ques_input, "answer": answer, "ChipAnswer": ChipAnswer})
        return render_template("answer_nchrp.html", user_name=session.get("user_name", ""), chat_history=_get_history())

    @nchrp_bp.route("/rating_submission", methods=["POST"])
    def rating_submission_nchrp():
        rating = request.form["rate"]
        rating2 = request.form["rate2"]
        question = session["question"]
        answer = session["answer"]
        user_email = session["user_email"]
        ChipAnswer = session["ChipAnswer"]

        mycursor_nchrp.execute("SELECT * FROM data")
        num_row = len(mycursor_nchrp.fetchall())

        sql = "INSERT INTO data VALUES (%s,%s,%s,%s,%s,%s,%s)"
        mycursor_nchrp.execute(sql, (num_row + 1, user_email, question, answer, rating, ChipAnswer, rating2))
        mydb_nchrp.commit()

        return render_template("answer_nchrp.html", user_name=session.get("user_name", ""), chat_history=_get_history())

    @nchrp_bp.route("/report")
    def testSampleReport():
        if "user_email" not in session:
            flash("Please log in first.")
            return redirect(url_for("nchrp_bp.index_nchrp"))
        tests, metrics = load_nchrp_from_files()
        meta_map = load_meta_index()
        return render_template(
            "testSample.html",
            column_headers=SUMMARY_COLS,
            tests=tests,
            metrics=metrics,
            meta_map=meta_map,
            user_role=session.get("user_role", "public"),
            user_name=session.get("user_name", "")
        )

    @nchrp_bp.route("/download-all-data")
    def download_all_data():
        sample_dir = os.path.join(current_app.root_path, "sampleData")
        upload_dir = os.path.join(current_app.root_path, "uploads")
        
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            # zip sampleData
            for root, dirs, files in os.walk(sample_dir):
                for f in files:
                    if f.startswith("~$") or f.startswith("."): continue
                    file_path = os.path.join(root, f)
                    arcname = os.path.relpath(file_path, current_app.root_path)
                    zf.write(file_path, arcname)
            # zip uploads
            if os.path.exists(upload_dir):
                for root, dirs, files in os.walk(upload_dir):
                    for f in files:
                        if f.startswith("~$") or f.startswith("."): continue
                        file_path = os.path.join(root, f)
                        arcname = os.path.relpath(file_path, current_app.root_path)
                        zf.write(file_path, arcname)

        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name="nchrp_dataset.zip"
        )

    @nchrp_bp.route("/download-template")
    def download_template():
        return send_from_directory(
            directory=os.path.join(current_app.root_path, "sampleData"),
            path="template.xlsx",
            as_attachment=True
        )

    @nchrp_bp.route("/download-source-file/<path:filename>")
    def download_source_file(filename):
        sample_dir = os.path.join(current_app.root_path, "sampleData")
        upload_excel_dir = os.path.join(current_app.root_path, "uploads", "excel")
        for directory in [sample_dir, upload_excel_dir]:
            if os.path.isfile(os.path.join(directory, filename)):
                return send_from_directory(directory, filename, as_attachment=True)
        return "File not found", 404

    @nchrp_bp.route("/download-source-files-zip", methods=["POST"])
    def download_source_files_zip():
        """Zip a requested list of source files and return as a single download."""
        filenames = request.json.get("files", []) if request.json else []
        if not filenames:
            return "No files requested", 400

        sample_dir = os.path.join(current_app.root_path, "sampleData")
        upload_excel_dir = os.path.join(current_app.root_path, "uploads", "excel")
        search_dirs = [sample_dir, upload_excel_dir]

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in filenames:
                safe = os.path.basename(fname)
                for d in search_dirs:
                    full = os.path.join(d, safe)
                    if os.path.isfile(full):
                        zf.write(full, safe)
                        break

        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype="application/zip",
            as_attachment=True,
            download_name="source_files.zip",
        )

    
    def _ext(name: str) -> str:
      return os.path.splitext(name)[1].lower()
    
    def load_meta_index() -> dict:
        meta_map = {}
        sample_meta_dir = os.path.join(current_app.root_path, "sampleData", "metadata")
        upload_meta_dir = os.path.join(current_app.root_path, "uploads", "metadata")
        
        for d in [sample_meta_dir, upload_meta_dir]:
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    if fn.startswith(".") or fn.startswith("~"): continue
                    # Extract Test ID from prefix (e.g. CAL-016_metadata.pdf -> CAL-016)
                    parts = fn.split("_")
                    if len(parts) > 1:
                        test_id = parts[0]
                    else:
                        test_id = fn.split(".")[0]
                    
                    test_id_lower = test_id.lower()
                    if test_id_lower not in meta_map:
                        meta_map[test_id_lower] = []
                    meta_map[test_id_lower].append(fn)

        return meta_map






    @nchrp_bp.route("/upload_report", methods=["POST"])
    def upload_report():
      upload_dir = os.path.join(current_app.root_path, "uploads")
      excel_dir = os.path.join(upload_dir, "excel")
      meta_dir = os.path.join(upload_dir, "metadata")

      os.makedirs(excel_dir, exist_ok=True)
      os.makedirs(meta_dir, exist_ok=True)

      report = request.files.get("report_file")
      meta = request.files.get("metadata_file")

      # --- required report file ---
      if not report or not report.filename:
          flash("Please upload the completed template file (.xlsx or .csv).")
          return redirect(url_for("nchrp_bp.testSampleReport"))

      report_name = secure_filename(report.filename)
      if _ext(report_name) not in ALLOWED_REPORT_EXT:
          flash("Report file must be .xlsx or .csv.")
          return redirect(url_for("nchrp_bp.testSampleReport"))

      # Save report into uploads/excel
      report_path = os.path.join(excel_dir, report_name)
      report.save(report_path)

      # --- optional metadata file ---
      uploaded_meta_name = None
      if meta and meta.filename:
          meta_name = secure_filename(meta.filename)
          if _ext(meta_name) not in ALLOWED_META_EXT:
              flash("Metadata file type not supported. Try PDF/DOC/DOCX/TXT/Images.")
              return redirect(url_for("nchrp_bp.testSampleReport"))

          # Save meta file with TestID naming convention intact
          meta_path = os.path.join(meta_dir, meta_name)
          meta.save(meta_path)
          uploaded_meta_name = meta_name

      # --- audit log to record uploader ---
      log_path = os.path.join(upload_dir, "upload_log.json")
      logs = []
      if os.path.exists(log_path):
          try:
              with open(log_path, "r") as f:
                  logs = json.load(f)
          except Exception:
              pass
      
      logs.append({
          "timestamp": datetime.now().isoformat(),
          "uploader_email": session.get("user_email", "unknown"),
          "uploader_name": session.get("user_name", "unknown"),
          "report_file": report_name,
          "metadata_file": uploaded_meta_name
      })

      try:
          with open(log_path, "w") as f:
              json.dump(logs, f, indent=2)
      except Exception as e:
          print(f"Failed to write upload log: {e}")

      # Rebuild SQLite DB so the AI immediately sees the new file
      build_db_from_files([excel_dir])

      flash("Upload successful!")
      return redirect(url_for("nchrp_bp.testSampleReport"))
    




    @nchrp_bp.route("/download-metadata/<path:filename>")
    def download_metadata(filename):
        upload_meta_dir = os.path.join(current_app.root_path, "uploads", "metadata")
        sample_meta_dir = os.path.join(current_app.root_path, "sampleData", "metadata")
        if os.path.isfile(os.path.join(upload_meta_dir, filename)):
            return send_from_directory(upload_meta_dir, filename, as_attachment=True)
        if os.path.isfile(os.path.join(sample_meta_dir, filename)):
            return send_from_directory(sample_meta_dir, filename, as_attachment=True)
        return "Metadata file not found", 404





    @nchrp_bp.route("/ask_ai", methods=["POST"])
    def ask_ai():
        print("\n" + "="*60)
        print("[ask_ai] ── REQUEST RECEIVED ──")

        # ── 1. Parse payload ──────────────────────────────────────
        payload = request.json or {}
        question = norm_str(payload.get("question", ""))
        print(f"[ask_ai] Raw payload keys : {list(payload.keys())}")
        print(f"[ask_ai] Question          : {repr(question)}")

        if not question:
            print("[ask_ai] ERROR: empty question – returning 400")
            return jsonify({"error": "No question provided"}), 400

        # ── 2. Run ask_excel ───────────────────────────────────────
        print("[ask_ai] Calling ask_excel() …")
        result = ask_excel(question)
        print(f"[ask_ai] ask_excel() returned:")
        print(f"  sql        : {result.get('sql', '')[:200]}")
        print(f"  columns    : {result.get('columns', [])}")
        print(f"  row count  : {len(result.get('rows', []))}")
        print(f"  error      : {result.get('error')}")
        print(f"  answer     : {result.get('answer', '')[:300]}")

        # ── 4. Meta-file lookup ────────────────────────────────────
        def find_meta_file(test_id_str):
            if not test_id_str:
                return None
            meta_dir = os.path.join(current_app.root_path, "sampleData", "metadata")
            if not os.path.exists(meta_dir):
                print(f"[ask_ai]   find_meta_file: metadata dir missing → {meta_dir}")
                return None
            for fn in os.listdir(meta_dir):
                if fn.startswith("~$") or fn.startswith("."): continue
                if fn.lower().startswith(test_id_str.lower()):
                    return fn
            return None

        cols = result.get("columns", [])
        csv_rows = []
        source_files = []
        for row in result.get("rows", []):
            d = dict(zip(cols, row))

            # wire source_file → __source__ so the download button works
            sf = d.get("source_file")
            if sf:
                d["__source__"] = sf
                if sf not in source_files:
                    source_files.append(sf)

            test_id = d.get("test_id") or d.get("Test ID", "")
            mfile = find_meta_file(test_id)
            if mfile:
                print(f"[ask_ai]   meta found: test_id={test_id!r} → {mfile}")
                d["__metadata_file__"] = mfile
            csv_rows.append(d)

        has_meta = any("__metadata_file__" in r for r in csv_rows)
        final_cols = cols + (["__metadata_file__"] if has_meta else [])
        print(f"[ask_ai] csv_rows count  : {len(csv_rows)}")
        print(f"[ask_ai] source files    : {source_files}")
        print(f"[ask_ai] final columns   : {final_cols}")
        print("[ask_ai] ── SENDING RESPONSE ──\n" + "="*60)

        return jsonify({
            "answer":        result["answer"],
            "matched_tests": [],
            "matched_rows":  csv_rows,
            "columns":       final_cols,
            "source_files":  source_files,
            "debug":         {"sql": result.get("sql")} if payload.get("debug") else None,
        })



    @nchrp_bp.route("/unified_chat", methods=["GET"])
    def unified_chat():
        if "user_email" not in session:
            flash("Please log in first.")
            return redirect(url_for("nchrp_bp.index_nchrp"))
        return render_template("unified_chat.html", user_name=session.get("user_name", ""))

    @nchrp_bp.route("/ask_unified_ai", methods=["POST"])
    def ask_unified_ai():
        payload = request.json or {}
        question = norm_str(payload.get("question", ""))

        if not question:
            return jsonify({"error": "No question provided"}), 400

        def pdf_answer_fn(q):
            vectorstore_nchrp = vectorstores.get("nchrp")
            if not vectorstore_nchrp:
                return "PDF source unavailable."
            try:
                answer_text, _ = answer_question(q, vectorstore_nchrp)
                return answer_text
            except Exception as e:
                print(f"[ERROR] PDF fetch failed: {e}")
                return "I don't know based on the documents."

        result = route_and_answer(question, pdf_answer_fn=pdf_answer_fn)

        if result.get("off_topic"):
            return jsonify({"off_topic": True}), 200

        return jsonify({
            "answer":         result["answer"],
            "route_decision": result.get("route", "EXCEL"),
            "has_excel":      bool(result.get("rows")),
            "has_pdf":        result.get("route", "") == "PDF",
        })

    return nchrp_bp
