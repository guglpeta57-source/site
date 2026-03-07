import os
from flask import Flask, request, jsonify, render_template, session
from flask_sqlalchemy import SQLAlchemy
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")

# Настройка PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)

# Создаём таблицы (выполняется один раз)
with app.app_context():
    db.create_all()

# Проверяем, что ключ API загружен
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("Не найден ключ API для GigaChat. Установите переменную окружения GIGACHAT_CREDENTIALS.")

# История сообщений
conversation_history = {}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Имя пользователя и пароль обязательны"}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Это имя пользователя уже занято"}), 400

    new_user = User(username=username, password=password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"success": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username, password=password).first()
    if not user:
        return jsonify({"error": "Неверное имя пользователя или пароль"}), 401

    session["user_id"] = user.id
    session["username"] = user.username

    return jsonify({"success": True, "username": user.username})

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    return jsonify({"success": True})

@app.route("/check_auth")
def check_auth():
    if "user_id" in session:
        return jsonify({"authenticated": True, "username": session["username"]})
    else:
        return jsonify({"authenticated": False})

@app.route("/ask", methods=["POST"])
def ask_gigachat():
    if "user_id" not in session:
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
        if session["user_id"] in conversation_history:
            conversation_history[session["user_id"]] = []
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

            if session["user_id"] in conversation_history:
                for msg in conversation_history[session["user_id"]]:
                    messages.append(msg)

            messages.append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )

            payload = Chat(messages=messages)
            response = giga.chat(payload)

            if session["user_id"] not in conversation_history:
                conversation_history[session["user_id"]] = []

            conversation_history[session["user_id"]].append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )
            conversation_history[session["user_id"]].append(
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
    if "user_id" in session and session["user_id"] in conversation_history:
        conversation_history[session["user_id"]] = []
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
