from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"

DB_NAME = "database.db"


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS masterclasses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        speaker TEXT,
        time TEXT,
        location TEXT,
        capacity INTEGER,
        registered_count INTEGER DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mc_id INTEGER,
        name TEXT,
        contact TEXT,
        status TEXT,
        waitlist_position INTEGER
    )
    """)

    conn.commit()

    # Демо данные
    cursor.execute("SELECT COUNT(*) FROM masterclasses")
    if cursor.fetchone()[0] == 0:
        demo_data = [
            ("Python для начинающих", "Иван Иванов", "10:00", "Аудитория 1", 3),
            ("AI и будущее", "Анна Смирнова", "12:00", "Аудитория 2", 2),
            ("Web-разработка", "Петр Петров", "14:00", "Аудитория 3", 4),
            ("DevOps основы", "Мария Соколова", "16:00", "Аудитория 4", 2),
        ]

        for mc in demo_data:
            cursor.execute(
                """
                INSERT INTO masterclasses (title, speaker, time, location, capacity)
                VALUES (?, ?, ?, ?, ?)
            """,
                mc,
            )

    conn.commit()
    conn.close()


@app.route("/")
def index():
    conn = get_db()
    mcs = conn.execute("SELECT * FROM masterclasses").fetchall()
    conn.close()
    return render_template("index.html", masterclasses=mcs)


@app.route("/register/<int:mc_id>", methods=["GET", "POST"])
def register(mc_id):
    conn = get_db()
    mc = conn.execute("SELECT * FROM masterclasses WHERE id = ?", (mc_id,)).fetchone()

    if request.method == "POST":
        name = request.form["name"]
        contact = request.form["contact"]

        if mc["registered_count"] < mc["capacity"]:
            status = "confirmed"
            waitlist_position = None

            conn.execute(
                """
                UPDATE masterclasses
                SET registered_count = registered_count + 1
                WHERE id = ?
            """,
                (mc_id,),
            )
        else:
            status = "waitlist"
            last_pos = conn.execute(
                """
                SELECT MAX(waitlist_position) FROM registrations WHERE mc_id = ? AND status = 'waitlist'
            """,
                (mc_id,),
            ).fetchone()[0]

            waitlist_position = 1 if last_pos is None else last_pos + 1

        conn.execute(
            """
            INSERT INTO registrations (mc_id, name, contact, status, waitlist_position)
            VALUES (?, ?, ?, ?, ?)
        """,
            (mc_id, name, contact, status, waitlist_position),
        )

        conn.commit()
        conn.close()

        return redirect(url_for("index"))

    conn.close()
    return render_template("register.html", mc=mc)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    if "admin" not in session:
        if request.method == "POST":
            password = request.form.get("password")
            if password == "admin123":
                session["admin"] = True
                return redirect(url_for("admin"))
        return """
        <form method="post" style="margin:50px">
            <input type="password" name="password" placeholder="Пароль">
            <button type="submit">Войти</button>
        </form>
        """

    conn = get_db()

    if request.method == "POST":
        title = request.form["title"]
        speaker = request.form["speaker"]
        time = request.form["time"]
        location = request.form["location"]
        capacity = request.form["capacity"]

        conn.execute(
            """
            INSERT INTO masterclasses (title, speaker, time, location, capacity)
            VALUES (?, ?, ?, ?, ?)
        """,
            (title, speaker, time, location, capacity),
        )

        conn.commit()

    mcs = conn.execute("SELECT * FROM masterclasses").fetchall()
    regs = conn.execute("""
        SELECT r.*, m.title 
        FROM registrations r
        JOIN masterclasses m ON r.mc_id = m.id
        ORDER BY r.mc_id, r.status DESC, r.waitlist_position ASC
    """).fetchall()

    conn.close()

    return render_template("admin.html", masterclasses=mcs, registrations=regs)


@app.route("/delete/<int:reg_id>")
def delete_registration(reg_id):
    conn = get_db()

    reg = conn.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,)).fetchone()
    mc_id = reg["mc_id"]

    if reg["status"] == "confirmed":
        conn.execute(
            """
            UPDATE masterclasses
            SET registered_count = registered_count - 1
            WHERE id = ?
        """,
            (mc_id,),
        )

        # Поднимаем первого из waitlist
        next_user = conn.execute(
            """
            SELECT * FROM registrations
            WHERE mc_id = ? AND status = 'waitlist'
            ORDER BY waitlist_position ASC
            LIMIT 1
        """,
            (mc_id,),
        ).fetchone()

        if next_user:
            conn.execute(
                """
                UPDATE registrations
                SET status = 'confirmed', waitlist_position = NULL
                WHERE id = ?
            """,
                (next_user["id"],),
            )

            conn.execute(
                """
                UPDATE masterclasses
                SET registered_count = registered_count + 1
                WHERE id = ?
            """,
                (mc_id,),
            )

            conn.execute(
                """
                UPDATE registrations
                SET waitlist_position = waitlist_position - 1
                WHERE mc_id = ? AND status = 'waitlist'
            """,
                (mc_id,),
            )

    else:
        conn.execute(
            """
            UPDATE registrations
            SET waitlist_position = waitlist_position - 1
            WHERE mc_id = ? AND waitlist_position > ?
        """,
            (mc_id, reg["waitlist_position"]),
        )

    conn.execute("DELETE FROM registrations WHERE id = ?", (reg_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("admin"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
