import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-change-me")

DATA_FILE = Path(__file__).parent / "registrations.json"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


def load_registrations():
    if not DATA_FILE.exists():
        return []
    try:
        with DATA_FILE.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []


def save_registrations(items):
    with DATA_FILE.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        message = (request.form.get("message") or "").strip()

        if not name or not email:
            flash("Name and email are required.", "error")
            return render_template(
                "register.html",
                name=name,
                email=email,
                message=message,
            )

        registrations = load_registrations()
        registrations.append({
            "id": len(registrations) + 1,
            "name": name,
            "email": email,
            "message": message,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        })
        save_registrations(registrations)

        flash("Registration successful!", "success")
        return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/admin", methods=["GET", "POST"])
def admin():
    authed = False
    error = None

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            authed = True
        else:
            error = "Invalid password."

    if not authed:
        return render_template("admin.html", authed=False, error=error)

    registrations = load_registrations()
    return render_template(
        "admin.html",
        authed=True,
        registrations=registrations,
        count=len(registrations),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
