import os
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import DictCursor
from werkzeug.security import generate_password_hash, check_password_hash

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")

# Проверяем, что ключ API загружен
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("Не найден ключ API для GigaChat. Установите переменную окружения GIGACHAT_CREDENTIALS.")

# Подключение к PostgreSQL
def get_db_connection():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    return conn

# История сообщений
conversation_history = {}

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        cur.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('home'))
        else:
            return jsonify({"error": "Неверное имя пользователя или пароль"}), 401

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password) VALUES (%s, %s)",
                (username, hashed_password)
            )
            conn.commit()
            return jsonify({"success": "Регистрация успешна! Теперь вы можете войти."}), 201
        except psycopg2.IntegrityError:
            return jsonify({"error": "Это имя пользователя уже занято"}), 400
        finally:
            cur.close()
            conn.close()

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/ask", methods=["POST"])
def ask_gigachat():
    if 'user_id' not in session:
        return jsonify({"error": "Требуется авторизация"}), 401

    data = request.json
    user_message = data.get("message")
    bot_role = data.get("role", "Ты — учитель, который общается с учеником напрямую. \
Отвечай на его вопросы понятно, кратко и по делу. \
Если ученик просит объяснить тему — давай примеры и проверяй понимание. \
Не имитируй диалог с другими учениками, общайся только с тем, кто тебе пишет.")

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    # Обработка команд
    if user_message.startswith("/help"):
        return jsonify({
            "answer": "📚 **Список команд:**\n\n"
                      "/help — показать этот список\n"
                      "/clear — очистить историю\n"
                      "/subject [предмет] — сменить предмет (например, /subject физика)\n"
                      "/example [тема] — попросить пример по теме (например, /example квадратные уравнения)"
        })

    elif user_message.startswith("/clear"):
        if session['user_id'] in conversation_history:
            conversation_history[session['user_id']] = []
        return jsonify({"answer": "🧹 История сообщений очищена!"})

    elif user_message.startswith("/subject"):
        subject = user_message[8:].strip()
        if subject:
            lines = bot_role.split('\n')
            if len(lines) >= 3:
                lines[2] = f"Сейчас ты ведёшь урок по предмету \"{subject}\" для 5 класса."
                bot_role = '\n'.join(lines)
                return jsonify({"answer": f"🔄 Предмет изменён на **{subject}**!"})
        else:
            return jsonify({"answer": "❌ Укажите предмет после команды. Пример: /subject физика"})

    elif user_message.startswith("/example"):
        topic = user_message[8:].strip()
        if topic:
            return jsonify({
                "answer": f"💡 **Пример по теме \"{topic}\":**\n\n"
                          f"(Здесь бот объяснит тему \"{topic}\" с примерами)"
            })
        else:
            return jsonify({"answer": "❌ Укажите тему после команды. Пример: /example логарифмы"})

    try:
        with GigaChat(
            credentials=GIGACHAT_CREDENTIALS,
            scope="GIGACHAT_API_PERS",
            verify_ssl_certs=False
        ) as giga:
            messages = [
                Messages(
                    role=MessagesRole.SYSTEM,
                    content=bot_role
                )
            ]

            if session['user_id'] in conversation_history:
                for msg in conversation_history[session['user_id']]:
                    messages.append(msg)

            messages.append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )

            payload = Chat(messages=messages)
            response = giga.chat(payload)

            if session['user_id'] not in conversation_history:
                conversation_history[session['user_id']] = []

            conversation_history[session['user_id']].append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )
            conversation_history[session['user_id']].append(
                Messages(
                    role=MessagesRole.ASSISTANT,
                    content=response.choices[0].message.content
                )
            )

            return jsonify({"answer": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": f"Ошибка: {str(e)}"}), 500

@app.route("/clear_history", methods=["POST"])
def clear_history():
    if 'user_id' not in session:
        return jsonify({"error": "Требуется авторизация"}), 401

    if session['user_id'] in conversation_history:
        conversation_history[session['user_id']] = []
    return jsonify({"status": "ok"})

# Инициализация базы данных
@app.before_first_request
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password VARCHAR(200) NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
