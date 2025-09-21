from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
from datetime import datetime

app = Flask(__name__)
CORS(app)

DB_NAME = "club_angel.db"


# ====== ХЭЛПЕРЫ ======
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ====== ИНИЦИАЛИЗАЦИЯ БАЗЫ ======
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Таблица пользователей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        playtime INTEGER DEFAULT 0
    )
    """)

    # Таблица консолей
    cur.execute("""
    CREATE TABLE IF NOT EXISTS consoles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    )
    """)

    # Таблица бронирований
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        console_id INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (console_id) REFERENCES consoles(id)
    )
    """)

    # Добавляем консоли, если их нет
    for c in ["PS 1", "PS 2", "PS 3", "PS 4", "PS 5"]:
        cur.execute("INSERT OR IGNORE INTO consoles (name) VALUES (?)", (c,))

    conn.commit()
    conn.close()


# ====== РЕГИСТРАЦИЯ ======
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Заполните все поля"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, hash_password(password)))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Пользователь уже существует"}), 400
    finally:
        conn.close()

    return jsonify({"message": "Регистрация успешна"}), 201


# ====== ЛОГИН ======
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cur.fetchone()
    conn.close()

    if user and user["password_hash"] == hash_password(password):
        return jsonify({"message": "Успешный вход", "user_id": user["id"]})
    else:
        return jsonify({"error": "Неверный логин или пароль"}), 401


# ====== БРОНИРОВАНИЕ ======
@app.route("/booking", methods=["POST"])
def booking():
    try:
        data = request.json
        username = data.get("username")
        console_id = data.get("console_id")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if not all([username, console_id, start_time, end_time]):
            return jsonify({"error": "Заполните все поля"}), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # Проверяем пользователя
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cur.fetchone()
        if not user:
            conn.close()
            return jsonify({"error": "Пользователь не найден"}), 404
        user_id = user["id"]

        # Проверяем консоль
        cur.execute("SELECT id FROM consoles WHERE id = ?", (console_id,))
        console = cur.fetchone()
        if not console:
            conn.close()
            return jsonify({"error": "Консоль не найдена!"}), 400

        # Проверяем конфликты бронирования
        cur.execute("""
            SELECT * FROM bookings
            WHERE console_id = ?
              AND start_time < ?
              AND end_time > ?
        """, (console_id, end_time, start_time))
        conflict = cur.fetchone()
        if conflict:
            conn.close()
            return jsonify({"error": "Консоль уже забронирована в это время!"}), 400

        # Сохраняем бронь
        cur.execute("""
            INSERT INTO bookings (user_id, console_id, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (user_id, console_id, start_time, end_time))
        conn.commit()
        conn.close()

        return jsonify({"message": "Бронь успешно создана!"})

    except Exception as e:
        print("🔥 Ошибка в booking:", e)
        return jsonify({"error": str(e)}), 500


# ====== ПОЛУЧЕНИЕ ВСЕХ БРОНИРОВАНИЙ ======
@app.route("/bookings", methods=["GET"])
def get_bookings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, u.username, b.console_id, b.start_time, b.end_time
        FROM bookings b
        JOIN users u ON b.user_id = u.id
    """)
    rows = cur.fetchall()
    conn.close()

    bookings = [dict(row) for row in rows]
    return jsonify(bookings)


# ====== Добавление времени (playtime) ======
@app.route("/add_playtime", methods=["POST"])
def add_playtime():
    data = request.json
    username = data.get("username")
    hours = data.get("hours", 1)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET playtime = playtime + ? WHERE username=?", (hours, username))
    conn.commit()
    conn.close()

    return jsonify({"message": f"{hours} ч. добавлено пользователю {username}"})


# ====== СТАРТ СЕРВЕРА ======
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
