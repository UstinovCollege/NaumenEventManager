from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Ключ для сессий (можно изменить)
DB_NAME = "database.db"


# --- Работа с БД ---
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Таблицы для мастер-классов и записей
    c.execute("""CREATE TABLE IF NOT EXISTS masterclasses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, speaker TEXT, time TEXT, location TEXT,
        capacity INTEGER, registered_count INTEGER DEFAULT 0)""")

    c.execute("""CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mc_id INTEGER, name TEXT, contact TEXT,
        status TEXT, waitlist_position INTEGER)""")

    # Таблица для вопросов от участников
    c.execute("""CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, contact TEXT, text TEXT,
        is_answered INTEGER DEFAULT 0, answer TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    # Таблицы для опросов
    c.execute("""CREATE TABLE IF NOT EXISTS polls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT, is_active INTEGER DEFAULT 1)""")

    c.execute("""CREATE TABLE IF NOT EXISTS poll_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER, option_text TEXT, votes INTEGER DEFAULT 0,
        FOREIGN KEY(poll_id) REFERENCES polls(id))""")

    conn.commit()

    # Заполняем демо-данными только если база пустая
    c.execute("SELECT COUNT(*) FROM masterclasses")
    if c.fetchone()[0] == 0:
        demo_mcs = [
            ("Python для начинающих", "Иван Иванов", "10:00", "Аудитория 1", 3),
            ("AI и будущее", "Анна Смирнова", "12:00", "Аудитория 2", 2),
            ("Web-разработка", "Петр Петров", "14:00", "Аудитория 3", 4),
            ("DevOps основы", "Мария Соколова", "16:00", "Аудитория 4", 2),
        ]
        for mc in demo_mcs:
            c.execute(
                "INSERT INTO masterclasses (title, speaker, time, location, capacity) VALUES (?,?,?,?,?)",
                mc,
            )

        # Демо-опрос
        c.execute(
            "INSERT INTO polls (question) VALUES ('Какой язык программирования вы предпочитаете?')"
        )
        poll_id = c.lastrowid
        c.executemany(
            "INSERT INTO poll_options (poll_id, option_text) VALUES (?,?)",
            [
                (poll_id, "Python"),
                (poll_id, "JavaScript"),
                (poll_id, "Go"),
                (poll_id, "Другой"),
            ],
        )

    conn.commit()
    conn.close()


# --- Маршруты ---


@app.route("/")
def index():
    conn = get_db()
    mcs = conn.execute("SELECT * FROM masterclasses ORDER BY time").fetchall()
    conn.close()
    return render_template("index.html", masterclasses=mcs)


@app.route("/status", methods=["GET", "POST"])
def check_status():
    if request.method == "POST":
        contact = request.form.get("contact", "").strip()
        if not contact:
            flash("Введите Email или Telegram", "error")
            return redirect(url_for("check_status"))

        conn = get_db()
        regs = conn.execute(
            """
            SELECT r.*, m.title, m.time, m.location 
            FROM registrations r JOIN masterclasses m ON r.mc_id = m.id 
            WHERE r.contact = ? ORDER BY m.time""",
            (contact,),
        ).fetchall()
        conn.close()

        if regs:
            flash(f"Найдено записей: {len(regs)}", "success")
        else:
            flash("Записей по этому контакту не найдено", "warning")

        return render_template("status.html", registrations=regs, contact=contact)
    return render_template("status.html", registrations=None)


@app.route("/register/<int:mc_id>", methods=["GET", "POST"])
def register(mc_id):
    conn = get_db()
    mc = conn.execute("SELECT * FROM masterclasses WHERE id = ?", (mc_id,)).fetchone()

    if not mc:
        conn.close()
        flash("Мастер-класс не найден", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()

        if not name or not contact:
            conn.close()
            return render_template("register.html", mc=mc, error="Заполните все поля")

        # Логика записи / листа ожидания
        if mc["registered_count"] < mc["capacity"]:
            status, waitlist_position = "confirmed", None
            conn.execute(
                "UPDATE masterclasses SET registered_count = registered_count + 1 WHERE id = ?",
                (mc_id,),
            )
        else:
            status = "waitlist"
            last_pos = conn.execute(
                """
                SELECT COALESCE(MAX(waitlist_position), 0)
                FROM registrations WHERE mc_id = ? AND status = 'waitlist'""",
                (mc_id,),
            ).fetchone()[0]
            waitlist_position = last_pos + 1

        conn.execute(
            """
            INSERT INTO registrations (mc_id, name, contact, status, waitlist_position)
            VALUES (?, ?, ?, ?, ?)""",
            (mc_id, name, contact, status, waitlist_position),
        )
        conn.commit()
        conn.close()

        msg = (
            "✅ Вы успешно записаны!"
            if status == "confirmed"
            else f"⏳ Вы в листе ожидания #{waitlist_position}"
        )
        category = "success" if status == "confirmed" else "warning"
        flash(msg, category)

        return render_template(
            "result.html",
            status=status,
            position=waitlist_position,
            mc_title=mc["title"],
        )

    conn.close()
    return render_template("register.html", mc=mc, error=None)


@app.route("/faq")
def faq():
    return render_template("faq.html")


@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        text = request.form.get("text", "").strip()

        if name and contact and text:
            conn = get_db()
            conn.execute(
                "INSERT INTO questions (name, contact, text) VALUES (?,?,?)",
                (name, contact, text),
            )
            conn.commit()
            conn.close()
            flash("✅ Вопрос отправлен организаторам!", "success")
            return redirect(url_for("feedback"))
        else:
            flash("Заполните все поля", "error")

    return render_template("feedback.html")


@app.route("/poll")
def poll_page():
    conn = get_db()
    polls = conn.execute("SELECT * FROM polls WHERE is_active=1").fetchall()

    poll_list = []
    for p in polls:
        # 1. Превращаем sqlite3.Row в обычный словарь
        poll_dict = dict(p)

        # 2. Загружаем варианты ответов
        opts = conn.execute(
            "SELECT * FROM poll_options WHERE poll_id=?", (poll_dict["id"],)
        ).fetchall()
        poll_dict["options"] = [dict(o) for o in opts]

        poll_list.append(poll_dict)

    conn.close()
    return render_template("poll.html", polls=poll_list)


@app.route("/poll/vote/<int:poll_id>", methods=["POST"])
def vote_poll(poll_id):
    option_id = request.form.get("option_id")
    if option_id:
        conn = get_db()
        conn.execute(
            "UPDATE poll_options SET votes = votes + 1 WHERE id = ?", (option_id,)
        )
        conn.commit()
        conn.close()
    return redirect(url_for("poll_results", poll_id=poll_id))


@app.route("/poll/results/<int:poll_id>")
def poll_results(poll_id):
    conn = get_db()
    poll = conn.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
    options = conn.execute(
        "SELECT * FROM poll_options WHERE poll_id=?", (poll_id,)
    ).fetchall()
    total = sum(o["votes"] for o in options) or 1
    conn.close()
    return render_template("poll_results.html", poll=poll, options=options, total=total)


@app.route("/admin", methods=["GET", "POST"])
def admin():
    # Проверка авторизации админа
    if "admin" not in session:
        if request.method == "POST":
            if request.form.get("password") == "admin123":
                session["admin"] = True
                return redirect(url_for("admin"))
            else:
                return render_template("login.html", error="Неверный пароль")
        return render_template("login.html", error=None)

    conn = get_db()

    # 1. Добавление мастер-класса
    if request.method == "POST" and "title" in request.form:
        title = request.form.get("title", "").strip()
        speaker = request.form.get("speaker", "").strip()
        time_val = request.form.get("time", "").strip()
        location = request.form.get("location", "").strip()
        capacity = request.form.get("capacity", type=int)

        if title and speaker and time_val and location and capacity:
            conn.execute(
                """
                INSERT INTO masterclasses (title, speaker, time, location, capacity)
                VALUES (?, ?, ?, ?, ?)""",
                (title, speaker, time_val, location, capacity),
            )
            conn.commit()
            flash("✅ Мастер-класс добавлен", "success")

    # 2. Создание опроса
    if request.method == "POST" and "poll_question" in request.form:
        question = request.form.get("poll_question", "").strip()
        options_str = request.form.get("poll_options", "").strip()

        if question and options_str:
            c = conn.cursor()
            c.execute("INSERT INTO polls (question) VALUES (?)", (question,))
            poll_id = c.lastrowid

            options = [opt.strip() for opt in options_str.split(",") if opt.strip()]
            for opt in options:
                c.execute(
                    "INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)",
                    (poll_id, opt),
                )

            conn.commit()
            flash("✅ Опрос успешно создан!", "success")
            return redirect(url_for("admin"))

    # 3. Ответ на вопрос участника
    if request.method == "POST" and "answer_question_id" in request.form:
        q_id = request.form.get("answer_question_id")
        answer = request.form.get("answer_text", "").strip()
        if q_id and answer:
            conn.execute(
                "UPDATE questions SET answer=?, is_answered=1 WHERE id=?",
                (answer, q_id),
            )
            conn.commit()
            flash("✅ Ответ сохранён", "success")

    # Получаем данные для отображения
    mcs = conn.execute("SELECT * FROM masterclasses ORDER BY time").fetchall()
    regs = conn.execute("""
        SELECT r.*, m.title FROM registrations r
        JOIN masterclasses m ON r.mc_id = m.id
        ORDER BY r.mc_id, r.status DESC, r.waitlist_position ASC""").fetchall()
    questions = conn.execute(
        "SELECT * FROM questions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    return render_template(
        "admin.html", masterclasses=mcs, registrations=regs, questions=questions
    )


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


@app.route("/delete/<int:reg_id>")
def delete_registration(reg_id):
    conn = get_db()
    reg = conn.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,)).fetchone()

    if not reg:
        conn.close()
        return redirect(url_for("admin"))

    mc_id = reg["mc_id"]

    # Если удаляем подтвержденного, переводим первого из waitlist
    if reg["status"] == "confirmed":
        conn.execute(
            "UPDATE masterclasses SET registered_count = registered_count - 1 WHERE id = ?",
            (mc_id,),
        )

        next_user = conn.execute(
            """
            SELECT * FROM registrations WHERE mc_id = ? AND status = 'waitlist'
            ORDER BY waitlist_position ASC LIMIT 1""",
            (mc_id,),
        ).fetchone()

        if next_user:
            conn.execute(
                """
                UPDATE registrations SET status = 'confirmed', waitlist_position = NULL
                WHERE id = ?""",
                (next_user["id"],),
            )
            conn.execute(
                "UPDATE masterclasses SET registered_count = registered_count + 1 WHERE id = ?",
                (mc_id,),
            )

            # Сдвигаем позиции остальных в очереди
            conn.execute(
                """
                UPDATE registrations SET waitlist_position = waitlist_position - 1
                WHERE mc_id = ? AND status = 'waitlist'""",
                (mc_id,),
            )
    else:
        # Если удаляем из waitlist, сдвигаем тех, кто ниже
        conn.execute(
            """
            UPDATE registrations SET waitlist_position = waitlist_position - 1
            WHERE mc_id = ? AND waitlist_position > ?""",
            (mc_id, reg["waitlist_position"]),
        )

    conn.execute("DELETE FROM registrations WHERE id = ?", (reg_id,))
    conn.commit()
    conn.close()

    flash("✅ Запись удалена", "success")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
