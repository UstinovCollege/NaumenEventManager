from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3

app = Flask(__name__)
app.secret_key = "supersecretkey"  # ключ для шифрования сессий
DB_NAME = "database.db"


# ПОДКЛЮЧЕНИЕ К БД
# sqlite3.connect открывает файл базы данных (создаёт если нет).
# row_factory = sqlite3.Row позволяет обращаться к колонкам по имени: row["title"]
# вместо row[0].

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# ИНИЦИАЛИЗАЦИЯ БД
# Создаёт таблицы при первом запуске. CREATE TABLE IF NOT EXISTS — безопасно
# вызывать каждый раз: таблица создаётся только если её ещё нет.
# В конце заполняет демо-данными если таблица masterclasses пуста.

def init_db():
    conn = get_db()
    c = conn.cursor()

    # таблица мастер-классов: вместимость и счётчик записавшихся
    c.execute("""CREATE TABLE IF NOT EXISTS masterclasses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, speaker TEXT, time TEXT, location TEXT,
        capacity INTEGER, registered_count INTEGER DEFAULT 0)""")

    # таблица записей: статус confirmed или waitlist, позиция в очереди
    c.execute("""CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mc_id INTEGER, name TEXT, contact TEXT,
        status TEXT, waitlist_position INTEGER)""")

    # таблица вопросов от участников
    c.execute("""CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, contact TEXT, text TEXT,
        is_answered INTEGER DEFAULT 0, answer TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

    # таблица опросов и вариантов ответов (связь один-ко-многим)
    c.execute("""CREATE TABLE IF NOT EXISTS polls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT, is_active INTEGER DEFAULT 1)""")

    c.execute("""CREATE TABLE IF NOT EXISTS poll_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER, option_text TEXT, votes INTEGER DEFAULT 0,
        FOREIGN KEY(poll_id) REFERENCES polls(id))""")

    conn.commit()

    # демо-данные добавляются только один раз при пустой таблице
    c.execute("SELECT COUNT(*) FROM masterclasses")
    if c.fetchone()[0] == 0:
        demo_mcs = [
            ("Python для начинающих", "Иван Иванов", "10:00", "Аудитория 1", 3),
            ("AI и будущее", "Анна Смирнова", "12:00", "Аудитория 2", 2),
            ("Web-разработка", "Петр Петров", "14:00", "Аудитория 3", 4),
            ("DevOps основы", "Мария Соколова", "16:00", "Аудитория 4", 2),
        ]
        for mc in demo_mcs:
            c.execute("INSERT INTO masterclasses (title, speaker, time, location, capacity) VALUES (?,?,?,?,?)", mc)

        # демо-опрос с вариантами
        c.execute("INSERT INTO polls (question) VALUES ('Какой язык программирования вы предпочитаете?')")
        poll_id = c.lastrowid
        c.executemany("INSERT INTO poll_options (poll_id, option_text) VALUES (?,?)", [
            (poll_id, "Python"), (poll_id, "JavaScript"), (poll_id, "Go"), (poll_id, "Другой")
        ])

    conn.commit()
    conn.close()


# ГЛАВНАЯ СТРАНИЦА
# Читает все мастер-классы из БД, сортирует по времени, передаёт в шаблон.
# render_template берёт HTML-файл из папки templates/ и подставляет переменные.

@app.route("/")
def index():
    conn = get_db()
    mcs = conn.execute("SELECT * FROM masterclasses ORDER BY time").fetchall()
    conn.close()
    return render_template("index.html", masterclasses=mcs)


# ПРОВЕРКА СТАТУСА ЗАПИСИ
# GET — показывает пустую форму.
# POST — ищет все записи участника по email/telegram (поле contact).
# JOIN объединяет таблицы registrations и masterclasses по mc_id.

@app.route("/status", methods=["GET", "POST"])
def check_status():
    if request.method == "POST":
        contact = request.form.get("contact", "").strip()
        if not contact:
            flash("Введите Email или Telegram", "error")
            return redirect(url_for("check_status"))

        conn = get_db()
        regs = conn.execute("""
            SELECT r.*, m.title, m.time, m.location 
            FROM registrations r JOIN masterclasses m ON r.mc_id = m.id 
            WHERE r.contact = ? ORDER BY m.time""", (contact,)).fetchall()
        conn.close()

        flash(f"Найдено записей: {len(regs)}", "success") if regs else flash("Записей не найдено", "warning")
        return render_template("status.html", registrations=regs, contact=contact)
    return render_template("status.html", registrations=None)


# ЗАПИСЬ НА МАСТЕР-КЛАСС
# GET — показывает форму с деталями МК.
# POST — проверяет наличие мест:
#   - если места есть: статус confirmed, счётчик +1
#   - если мест нет: статус waitlist, вычисляет следующую позицию в очереди
# ? в SQL-запросах — защита от SQL-инъекций (параметризованные запросы).

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

        if mc["registered_count"] < mc["capacity"]:
            # место есть — подтверждаем и увеличиваем счётчик
            status, waitlist_position = "confirmed", None
            conn.execute("UPDATE masterclasses SET registered_count = registered_count + 1 WHERE id = ?", (mc_id,))
        else:
            # мест нет — ставим в очередь после последней занятой позиции
            status = "waitlist"
            last_pos = conn.execute("""
                SELECT COALESCE(MAX(waitlist_position), 0)
                FROM registrations WHERE mc_id = ? AND status = 'waitlist'""", (mc_id,)).fetchone()[0]
            waitlist_position = last_pos + 1

        conn.execute("""
            INSERT INTO registrations (mc_id, name, contact, status, waitlist_position)
            VALUES (?, ?, ?, ?, ?)""", (mc_id, name, contact, status, waitlist_position))
        conn.commit()
        conn.close()

        msg = "✅ Вы успешно записаны!" if status == "confirmed" else f"⏳ Лист ожидания #{waitlist_position}"
        flash(msg, "success" if status == "confirmed" else "warning")
        return render_template("result.html", status=status, position=waitlist_position, mc_title=mc["title"])

    conn.close()
    return render_template("register.html", mc=mc, error=None)


# УДАЛЕНИЕ МАСТЕР-КЛАССА (АДМИН)
# Проверяет сессию — если admin не в session, редиректит на главную.
# Удаляет сначала связанные записи, потом сам МК (порядок важен для целостности).

@app.route("/admin/delete_mc/<int:mc_id>")
def delete_mc(mc_id):
    if "admin" not in session:
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("DELETE FROM registrations WHERE mc_id = ?", (mc_id,))
    conn.execute("DELETE FROM masterclasses WHERE id = ?", (mc_id,))
    conn.commit()
    conn.close()
    flash("Мастер-класс удалён", "warning")
    return redirect(url_for("admin"))


# FAQ
# Статическая страница — просто рендерит шаблон без запросов к БД.

@app.route("/faq")
def faq():
    return render_template("faq.html")


# ФОРМА ОБРАТНОЙ СВЯЗИ
# POST — сохраняет вопрос участника в таблицу questions.
# Организатор видит вопросы в админке и может ответить на них.

@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        contact = request.form.get("contact", "").strip()
        text = request.form.get("text", "").strip()

        if name and contact and text:
            conn = get_db()
            conn.execute("INSERT INTO questions (name, contact, text) VALUES (?,?,?)", (name, contact, text))
            conn.commit()
            conn.close()
            flash("✅ Вопрос отправлен!", "success")
            return redirect(url_for("feedback"))
        flash("Заполните все поля", "error")
    return render_template("feedback.html")


# СТРАНИЦА ГОЛОСОВАНИЯ
# Загружает только активные опросы (is_active=1).
# Для каждого опроса отдельным запросом подгружает варианты ответов.
# dict(p) конвертирует sqlite3.Row в словарь, чтобы добавить ключ options.

@app.route("/poll")
def poll_page():
    conn = get_db()
    polls_raw = conn.execute("SELECT * FROM polls WHERE is_active=1").fetchall()
    polls = []
    for p in polls_raw:
        pd = dict(p)
        pd["options"] = [dict(o) for o in conn.execute("SELECT * FROM poll_options WHERE poll_id=?", (pd["id"],)).fetchall()]
        polls.append(pd)
    conn.close()
    return render_template("poll.html", polls=polls)


# ГОЛОСОВАНИЕ
# Принимает выбранный вариант (option_id), увеличивает счётчик votes на 1.
# После голосования редиректит на страницу результатов.

@app.route("/poll/vote/<int:poll_id>", methods=["POST"])
def vote_poll(poll_id):
    option_id = request.form.get("option_id")
    if option_id:
        conn = get_db()
        conn.execute("UPDATE poll_options SET votes = votes + 1 WHERE id = ?", (option_id,))
        conn.commit()
        conn.close()
    return redirect(url_for("poll_results", poll_id=poll_id))


# РЕЗУЛЬТАТЫ ГОЛОСОВАНИЯ 
# Считает total голосов для вычисления процентов в шаблоне.
# or 1 защищает от деления на ноль если никто не голосовал.

@app.route("/poll/results/<int:poll_id>")
def poll_results(poll_id):
    conn = get_db()
    poll = conn.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
    options = conn.execute("SELECT * FROM poll_options WHERE poll_id=?", (poll_id,)).fetchall()
    total = sum(o["votes"] for o in options) or 1
    conn.close()
    return render_template("poll_results.html", poll=poll, options=options, total=total)


# ПАНЕЛЬ ОРГАНИЗАТОРА
# Защищена паролем через сессию.
# Сессия — это зашифрованная куки в браузере. Если "admin" есть в session —
# пользователь авторизован. Сессия хранится пока не закрыт браузер или не вызван logout.
#
# Обрабатывает три POST-действия по наличию ключа в request.form:
#   1. "title" в форме → добавить МК
#   2. "poll_question" в форме → создать опрос
#   3. "answer_question_id" в форме → ответить на вопрос участника

@app.route("/admin", methods=["GET", "POST"])
def admin():
    # проверка авторизации — пароль сравнивается напрямую со строкой
    if "admin" not in session:
        if request.method == "POST" and request.form.get("password") == "admin123":
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error=None)

    conn = get_db()

    # действие 1: добавить мастер-класс
    if request.method == "POST" and "title" in request.form:
        t, s, tm, l, c = (request.form.get(k, "").strip() for k in ["title", "speaker", "time", "location"])
        cap = request.form.get("capacity", type=int)
        if t and s and tm and l and cap:
            conn.execute("INSERT INTO masterclasses (title, speaker, time, location, capacity) VALUES (?,?,?,?,?)", (t, s, tm, l, cap))
            conn.commit()
            flash("✅ МК добавлен", "success")

    # действие 2: создать опрос с вариантами (варианты — через запятую)
    if request.method == "POST" and "poll_question" in request.form:
        q = request.form.get("poll_question", "").strip()
        opts_str = request.form.get("poll_options", "").strip()
        if q and opts_str:
            cur = conn.cursor()
            cur.execute("INSERT INTO polls (question) VALUES (?)", (q,))
            pid = cur.lastrowid
            for opt in [o.strip() for o in opts_str.split(",") if o.strip()]:
                cur.execute("INSERT INTO poll_options (poll_id, option_text) VALUES (?,?)", (pid, opt))
            conn.commit()
            flash("✅ Опрос создан", "success")
            return redirect(url_for("admin"))

    # действие 3: сохранить ответ на вопрос участника
    if request.method == "POST" and "answer_question_id" in request.form:
        qid = request.form.get("answer_question_id")
        ans = request.form.get("answer_text", "").strip()
        if qid and ans:
            conn.execute("UPDATE questions SET answer=?, is_answered=1 WHERE id=?", (ans, qid))
            conn.commit()
            flash("✅ Ответ сохранён", "success")

    # загрузка всех данных для отображения в панели
    mcs = conn.execute("SELECT * FROM masterclasses ORDER BY time").fetchall()
    regs = conn.execute("""
        SELECT r.*, m.title FROM registrations r
        JOIN masterclasses m ON r.mc_id = m.id
        ORDER BY r.mc_id, r.status DESC, r.waitlist_position ASC""").fetchall()
    questions = conn.execute("SELECT * FROM questions ORDER BY created_at DESC").fetchall()

    # опросы с подсчётом вариантов (для отображения количества опций)
    polls_raw = conn.execute("SELECT * FROM polls ORDER BY id DESC").fetchall()
    polls = []
    for p in polls_raw:
        pd = dict(p)
        pd["options_count"] = conn.execute(
            "SELECT COUNT(*) FROM poll_options WHERE poll_id=?", (pd["id"],)
        ).fetchone()[0]
        polls.append(pd)

    conn.close()
    return render_template("admin.html", masterclasses=mcs, registrations=regs, questions=questions, polls=polls)


# ВЫХОД
# Удаляет ключ "admin" из сессии — пользователь разлогинивается.

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


# УДАЛЕНИЕ ЗАПИСИ (АДМИН)
# Если удаляемая запись была confirmed — место освобождается.
# Первый из waitlist автоматически получает статус confirmed.
# Позиции остальных в очереди сдвигаются на -1.
# Если удаляемый был в waitlist — просто сдвигаем позиции тех кто стоял после него.

@app.route("/delete/<int:reg_id>")
def delete_registration(reg_id):
    conn = get_db()
    reg = conn.execute("SELECT * FROM registrations WHERE id = ?", (reg_id,)).fetchone()
    if not reg:
        conn.close()
        return redirect(url_for("admin"))

    mc_id = reg["mc_id"]
    if reg["status"] == "confirmed":
        # освобождаем место
        conn.execute("UPDATE masterclasses SET registered_count = registered_count - 1 WHERE id = ?", (mc_id,))
        # берём первого из очереди ожидания
        nxt = conn.execute("SELECT * FROM registrations WHERE mc_id=? AND status='waitlist' ORDER BY waitlist_position ASC LIMIT 1", (mc_id,)).fetchone()
        if nxt:
            conn.execute("UPDATE registrations SET status='confirmed', waitlist_position=NULL WHERE id=?", (nxt["id"],))
            conn.execute("UPDATE masterclasses SET registered_count = registered_count + 1 WHERE id = ?", (mc_id,))
            conn.execute("UPDATE registrations SET waitlist_position = waitlist_position - 1 WHERE mc_id=? AND status='waitlist'", (mc_id,))
    else:
        # удаляем из очереди — сдвигаем позиции тех кто стоял после
        conn.execute("UPDATE registrations SET waitlist_position = waitlist_position - 1 WHERE mc_id=? AND waitlist_position>?", (mc_id, reg["waitlist_position"]))

    conn.execute("DELETE FROM registrations WHERE id = ?", (reg_id,))
    conn.commit()
    conn.close()
    flash("✅ Запись удалена", "success")
    return redirect(url_for("admin"))


# УДАЛЕНИЕ ОПРОСА (АДМИН)
# Сначала удаляет варианты ответов, потом сам опрос (порядок важен).

@app.route("/admin/delete_poll/<int:poll_id>")
def delete_poll(poll_id):
    if "admin" not in session:
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("DELETE FROM poll_options WHERE poll_id=?", (poll_id,))
    conn.execute("DELETE FROM polls WHERE id=?", (poll_id,))
    conn.commit()
    conn.close()
    flash("Опрос удалён", "warning")
    return redirect(url_for("admin"))


# ЗАПУСК ПРИЛОЖЕНИЯ

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)