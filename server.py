#!/usr/bin/env python3
# server.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
from datetime import datetime
import math
import os

app = Flask(__name__)
CORS(app)

DB_NAME = "club_angel.db"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"  # ожидаемый формат start_time / end_time


# ---------- Helpers ----------
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_db_dir():
    # если нужно: создаём папку для БД (опционально)
    db_dir = os.path.dirname(os.path.abspath(DB_NAME))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


# ---------- Init DB ----------
def init_db():
    ensure_db_dir()
    conn = get_db_connection()
    cur = conn.cursor()

    # users (password_hash, playtime хранится в часах)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            playtime INTEGER DEFAULT 0,
            email TEXT,
            phone TEXT
        )
    """)

    # consoles
    cur.execute("""
        CREATE TABLE IF NOT EXISTS consoles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    # bookings
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            console_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(console_id) REFERENCES consoles(id)
        )
    """)

    # seed consoles
    for name in ["PS 1", "PS 2", "PS 3", "PS 4", "PS 5"]:
        cur.execute("INSERT OR IGNORE INTO consoles (name) VALUES (?)", (name,))

    conn.commit()
    conn.close()


# ---------- Routes ----------

@app.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    app.logger.debug("📥 Register request: %s", data)

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, hash_password(password)))
        conn.commit()
        user_id = cur.lastrowid
        return jsonify({"message": "user created", "user_id": user_id}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "username already exists"}), 400
    except Exception as e:
        app.logger.exception("register error")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()

    if row and row["password_hash"] == hash_password(password):
        return jsonify({"message": "ok", "user_id": row["id"]}), 200
    else:
        return jsonify({"error": "invalid credentials"}), 401


@app.route("/get_profile", methods=["GET"])
def get_profile():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "username required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email, phone, playtime FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "user not found"}), 404

    return jsonify(dict(row)), 200


@app.route("/update_profile", methods=["POST"])
def update_profile():
    data = request.json or {}
    username = data.get("username")
    email = data.get("email")
    phone = data.get("phone")

    if not username:
        return jsonify({"error": "username required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET email = ?, phone = ? WHERE username = ?", (email, phone, username))
        conn.commit()
        return jsonify({"message": "profile updated"}), 200
    except Exception as e:
        app.logger.exception("update_profile error")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route("/consoles", methods=["GET"])
def list_consoles():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM consoles ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    consoles = [dict(r) for r in rows]
    return jsonify(consoles)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id, u.username, c.name as console, b.start_time, b.end_time, b.created_at
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN consoles c ON b.console_id = c.id
        ORDER BY b.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/booking", methods=["POST"])
def booking():
    """
    Ожидает JSON:
    {
      "username": "test_user",
      "console_id": 2,
      "start_time": "2025-10-01 16:00:00",
      "end_time": "2025-10-01 18:00:00"
    }
    Автоматически добавляет (end-start) часов в users.playtime.
    """
    try:
        data = request.json or {}
        app.logger.debug("📥 Booking request: %s", data)

        username = data.get("username")
        console_id = data.get("console_id")
        start_time = data.get("start_time")
        end_time = data.get("end_time")

        if not all([username, console_id, start_time, end_time]):
            return jsonify({"error": "username, console_id, start_time, end_time required"}), 400

        # парсим времена
        try:
            t1 = datetime.strptime(start_time, DATETIME_FMT)
            t2 = datetime.strptime(end_time, DATETIME_FMT)
        except Exception as e:
            return jsonify({"error": f"time format must be '{DATETIME_FMT}'"}), 400

        if t2 <= t1:
            return jsonify({"error": "end_time must be after start_time"}), 400

        # считаем часы (по умолчанию округляем вниз до целых часов)
        seconds = (t2 - t1).total_seconds()
        added_hours = int(seconds // 3600)

        # если хочешь округлять вверх до ближайшего часа, раскомментируй:
        # added_hours = math.ceil(seconds / 3600)

        if added_hours <= 0:
            # если длина меньше часа, по умолчанию добавим 1 час (можно изменить)
            added_hours = 1

        conn = get_db_connection()
        cur = conn.cursor()

        # получаем user_id
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_row = cur.fetchone()
        if not user_row:
            conn.close()
            return jsonify({"error": "user not found"}), 404
        user_id = user_row["id"]

        # проверяем консоль
        cur.execute("SELECT id FROM consoles WHERE id = ?", (console_id,))
        console_row = cur.fetchone()
        if not console_row:
            conn.close()
            return jsonify({"error": "console not found"}), 404

        # проверка пересечения (сравниваем строками ISO-формата — безопасно если формат фиксированный)
        cur.execute("""
            SELECT 1 FROM bookings
            WHERE console_id = ?
              AND start_time < ?
              AND end_time > ?
            LIMIT 1
        """, (console_id, end_time, start_time))
        conflict = cur.fetchone()
        if conflict:
            conn.close()
            return jsonify({"error": "console already booked in this time range"}), 400

        # вставляем бронь и обновляем playtime в рамках одной транзакции
        cur.execute("""
            INSERT INTO bookings (user_id, console_id, start_time, end_time)
            VALUES (?, ?, ?, ?)
        """, (user_id, console_id, start_time, end_time))

        cur.execute("UPDATE users SET playtime = playtime + ? WHERE id = ?", (added_hours, user_id))

        conn.commit()
        conn.close()

        app.logger.info("✅ Booking saved for user_id=%s, console_id=%s, added_hours=%s", user_id, console_id, added_hours)

        return jsonify({"message": "booking saved", "added_hours": added_hours}), 200

    except Exception as e:
        app.logger.exception("booking error")
        return jsonify({"error": str(e)}), 500


@app.route("/add_playtime", methods=["POST"])
def add_playtime():
    """
    Optional endpoint — можно добавить часы вручную.
    JSON: { "username": "test_user", "hours": 2 }
    """
    try:
        data = request.json or {}
        username = data.get("username")
        hours = int(data.get("hours", 0))

        if not username or hours <= 0:
            return jsonify({"error": "username and positive hours required"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET playtime = playtime + ? WHERE username = ?", (hours, username))
        conn.commit()
        conn.close()

        return jsonify({"message": f"{hours} hours added to {username}"}), 200
    except Exception as e:
        app.logger.exception("add_playtime error")
        return jsonify({"error": str(e)}), 500


@app.route("/playtime", methods=["POST"])
def playtime():
    """
    Получить текущее playtime пользователя.
    JSON: { "username": "test_user" }
    Ответ: { "play_time": 10 }
    """
    try:
        data = request.json or {}
        username = data.get("username")
        if not username:
            return jsonify({"error": "username required"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT playtime FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        conn.close()

        if not row:
            return jsonify({"error": "user not found"}), 404

        return jsonify({"play_time": row["playtime"]}), 200
    except Exception as e:
        app.logger.exception("playtime error")
        return jsonify({"error": str(e)}), 500


# ---------- run ----------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
