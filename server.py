from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import hashlib
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

DB_NAME = "club_angel.db"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"


# ---------- Helpers ----------
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_db_dir():
    db_dir = os.path.dirname(os.path.abspath(DB_NAME))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


# ---------- Init DB ----------
def init_db():
    ensure_db_dir()
    conn = get_db_connection()
    cur = conn.cursor()

    # Таблица пользователей
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            playtime REAL DEFAULT 0,
            email TEXT,
            phone TEXT
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(console_id) REFERENCES consoles(id)
        )
    """)

    # Seed консолей
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

    if not username or not password:
        return jsonify({"error": "username and password required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password))
        )
        conn.commit()
        return jsonify({"message": "user created", "user_id": cur.lastrowid}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "username already exists"}), 400
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
    return jsonify({"error": "invalid credentials"}), 401


@app.route("/get_profile", methods=["GET"])
def get_profile():
    username = request.args.get("username")
    if not username:
        return jsonify({"error": "username required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, email, phone, playtime FROM users WHERE username = ?",
        (username,)
    )
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
    cur.execute(
        "UPDATE users SET email = ?, phone = ? WHERE username = ?",
        (email, phone, username)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "profile updated"}), 200


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
    username = request.args.get("username")  # Можно фильтровать по пользователю
    conn = get_db_connection()
    cur = conn.cursor()
    query = """
        SELECT b.id, u.username, c.name as console, b.start_time, b.end_time, b.created_at
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        JOIN consoles c ON b.console_id = c.id
    """
    params = ()
    if username:
        query += " WHERE u.username = ?"
        params = (username,)
    query += " ORDER BY b.created_at DESC"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/booking", methods=["POST"])
def booking():
    data = request.json or {}
    username = data.get("username")
    console_id = data.get("console_id")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    hours = data.get("hours")

    if not all([username, console_id, start_time, end_time]):
        return jsonify({"error": "username, console_id, start_time, end_time required"}), 400

    try:
        t1 = datetime.strptime(start_time, DATETIME_FMT)
        t2 = datetime.strptime(end_time, DATETIME_FMT)
    except Exception:
        return jsonify({"error": f"time format must be '{DATETIME_FMT}'"}), 400

    if t2 <= t1:
        return jsonify({"error": "end_time must be after start_time"}), 400

    added_hours = hours if hours else (t2 - t1).total_seconds() / 3600
    if added_hours <= 0:
        added_hours = 0.5

    conn = get_db_connection()
    cur = conn.cursor()

    # Получаем user_id
    cur.execute("SELECT id FROM users WHERE username = ?", (username,))
    user_row = cur.fetchone()
    if not user_row:
        conn.close()
        return jsonify({"error": "user not found"}), 404
    user_id = user_row["id"]

    # Проверка консоли
    cur.execute("SELECT id FROM consoles WHERE id = ?", (console_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({"error": "console not found"}), 404

    # Проверка пересечения бронирований
    cur.execute("""
        SELECT 1 FROM bookings
        WHERE console_id = ?
          AND start_time < ?
          AND end_time > ?
        LIMIT 1
    """, (console_id, end_time, start_time))
    if cur.fetchone():
        conn.close()
        return jsonify({"error": "console already booked in this time range"}), 400

    # Вставка брони и обновление playtime
    cur.execute(
        "INSERT INTO bookings (user_id, console_id, start_time, end_time) VALUES (?, ?, ?, ?)",
        (user_id, console_id, start_time, end_time)
    )
    cur.execute(
        "UPDATE users SET playtime = playtime + ? WHERE id = ?",
        (added_hours, user_id)
    )

    conn.commit()
    conn.close()
    return jsonify({"message": "booking saved", "added_hours": added_hours}), 200


@app.route("/add_playtime", methods=["POST"])
def add_playtime():
    data = request.json or {}
    username = data.get("username")
    hours = float(data.get("hours", 0))

    if not username or hours <= 0:
        return jsonify({"error": "username and positive hours required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET playtime = playtime + ? WHERE username = ?", (hours, username))
    conn.commit()
    conn.close()
    return jsonify({"message": f"{hours} hours added to {username}"}), 200


@app.route("/playtime", methods=["POST"])
def playtime():
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


# ---------- Run ----------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
