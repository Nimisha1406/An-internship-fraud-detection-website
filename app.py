# -*- coding: utf-8 -*-
"""
Created on Sat Mar 21 17:09:27 2026

@author: nanda
"""

from flask import Flask, render_template, request, redirect, session
import sqlite3, random, pickle, os
import numpy as np
from PIL import Image
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

app = Flask(__name__)
app.secret_key = "secretkey"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load ML objects (scikit-learn)
model = pickle.load(open("model.pkl", "rb"))
vectorizer = pickle.load(open("vectorizer.pkl", "rb"))


def extract_details(text):
    import re

    text = text.lower()

   # -------- STIPEND --------
    stipend = 0

    text = text.lower()

    # Step 1: Find ALL numbers (including broken OCR like 23 000)
    numbers = re.findall(r'\d[\d, ]{2,10}', text)
    clean_numbers = []
    for n in numbers:
        clean = re.sub(r'[^0-9]', '', n)
        if clean:
            val = int(clean)
            clean_numbers.append(val)

    # Step 2: PRIORITY → numbers near "stipend"
    stipend_block = re.search(r'.{0,50}stipend.{0,50}', text)
    if stipend_block:
        block = stipend_block.group()
        nums = re.findall(r'\d[\d, ]{2,10}', block)
        for n in nums:
            clean = re.sub(r'[^0-9]', '', n)
            if clean:
                val = int(clean)
                if 1000 <= val <= 100000:
                    stipend = val
                    break
    # Step 3: Fallback → pick BEST candidate (ignore dates like 2026)
    if stipend == 0 and clean_numbers:
        for val in clean_numbers:
            # ignore common year-like values
            if val in [2024, 2025, 2026, 2027]:
                continue
            if 1000 <= val <= 100000:
                stipend = val
                break
    
   # -------- FEE --------
    fee = 0
    
    fee_match = re.search(
        r'(registration fee|application fee|fee|payment)\s*(is|:)?\s*₹?\s*([\d,]{3,6})',
        text,
        re.IGNORECASE
        )
    if fee_match:
        fee = int(fee_match.group(3).replace(",", ""))

    # -------- EMAIL --------
    if "@gmail.com" in text or "@yahoo.com" in text:
        official_email = 0
    else:
        official_email = 1

    return official_email, stipend, fee

# Database
def get_db():
    return sqlite3.connect("users.db")

with get_db() as db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            email TEXT PRIMARY KEY,
            phone TEXT,
            password TEXT,
            verified INTEGER
        )
    """)

# ---------------- SIGNUP ----------------
@app.route("/", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        # If user already exists → go to login
        if user:
            return redirect("/login?msg=User already exists")

        #If new user → insert
        db.execute(
            "INSERT INTO users VALUES (?,?,?,?)",
            (email, phone, password, 1)
        )
        db.commit()

        return redirect("/login")

    return render_template("signup.html")

# ---------------- LOGIN ----------------
from flask import flash

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email=? AND password=?",
            (email,password)
        ).fetchone()

        if user:
            session["user"] = email
            return redirect("/dashboard")
        else:
            flash("Invalid email or password. Please try again.")
            return redirect("/login")

    return render_template("login.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    print("Dashboard route hit")
    #if "user" not in session:
    #   return redirect("/login")

    if request.method == "POST":
        print("POST request received")
        file = request.files.get("file")
        print(file)

        if file:
            filename = file.filename

            # Read text file
            if filename.endswith(".txt"):
                text = file.read().decode("utf-8")

            # Read image file
            elif filename.endswith((".png", ".jpg", ".jpeg")):
                image = Image.open(file)
                # Improve OCR accuracy
                image=image.resize((image.width*2,image.height*2))

                image = image.convert('L')   # grayscale
                # Increase contrast 
                import numpy as np
                image = np.array(image)
                image = (image > 150) * 255   # thresholding
                image = Image.fromarray(image.astype('uint8'))
                #OCR config
                custom_config = r'--oem 3 --psm 6'
                text = pytesseract.image_to_string(image, config=custom_config)
                #Clean text
                import re
                text = re.sub(r'[^a-zA-Z0-9₹.,:/@ ]+', ' ', text)
                #Clean each line
                lines = text.split('\n')
                clean_lines=[line.strip() for line in lines if line.strip()!= ""]
                text = "\n".join(clean_lines)
                print("CLEAN OCR TEXT:\n", text)
            else:
                return "Unsupported file type"

            # Extract data automatically
            official_email, stipend, fee = extract_details(text)

            # ML prediction
            features = vectorizer.transform([text])
            proba = model.predict_proba(features)[0]
            confidence = max(proba) * 100
            prediction = np.argmax(proba)

            # Rule-based fraud detection
            fraud_keywords = [
            "pay", "registration fee", "limited seats", "last chance",
            "hurry", "urgent", "final day", "only few", "vacancy left",
             "click link", "rzp.io", "payment", "enroll now"
            ]

            is_fraud_rule = any(word in text.lower() for word in fraud_keywords)

            # Final decision
            if prediction == 1 or is_fraud_rule:
                result = f"FRAUD ({confidence:.2f}%)"
            else:
                result = f"LEGIT ({confidence:.2f}%)"

            return render_template("dashboard.html",
                                   result=result,
                                   extracted_text=text,
                                   stipend=stipend,
                                   fee=fee)

    return render_template("dashboard.html")

app.run(debug=True)