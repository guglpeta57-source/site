import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey123")  # Обязательно измените в Railway!

# Подключение к PostgreSQL
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Модель пользователя
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Создание таблиц (если не существуют)
with app.app_context():
    db.create_all()

# Проверка ключа GigaChat
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("Не найден ключ API для GigaChat. Установите переменную окружения GIGACHAT_CREDENTIALS.")

# История сообщений (для каждого пользователя)
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
        return jsonify({"error": "Пользователь с таким именем уже существует"}), 400

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"success": True})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
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
    return jsonify({"authenticated": False})

# ----- Новые маршруты для профиля -----
@app.route("/profile")
def profile():
    if "user_id" not in session:
        return jsonify({"error": "Не авторизован"}), 401
    user = User.query.get(session["user_id"])
    if not user:
        return jsonify({"error": "Пользователь не найден"}), 404
    return jsonify({
        "id": user.id,
        "username": user.username,
        "created_at": user.created_at.isoformat() if user.created_at else None
    })

@app.route("/change_password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return jsonify({"error": "Не авторизован"}), 401
    data = request.json
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    if not old_password or not new_password:
        return jsonify({"error": "Старый и новый пароль обязательны"}), 400
    user = User.query.get(session["user_id"])
    if not user or not user.check_password(old_password):
        return jsonify({"error": "Неверный старый пароль"}), 401
    user.set_password(new_password)
    db.session.commit()
    return jsonify({"success": True})
# --------------------------------------

@app.route("/ask", methods=["POST"])
def ask_gigachat():
    if "user_id" not in session:
        return jsonify({"error": "Требуется авторизация"}), 401

    data = request.json
    user_message = data.get("message")
    bot_role = data.get("role", "Ты — учитель, который общается с учеником напрямую. Отвечай понятно, кратко и по делу.")

    if not user_message:
        return jsonify({"error": "Пустое сообщение"}), 400

    # Простые команды
    if user_message.startswith("/help"):
        return jsonify({"answer": "Доступные команды: /clear – очистить историю, /help – помощь"})
    if user_message.startswith("/clear"):
        if session["user_id"] in conversation_history:
            conversation_history[session["user_id"]] = []
        return jsonify({"answer": "История очищена"})

    try:
        with GigaChat(credentials=GIGACHAT_CREDENTIALS, scope="GIGACHAT_API_PERS", verify_ssl_certs=False) as giga:
            messages = [Messages(role=MessagesRole.SYSTEM, content=bot_role)]
            if session["user_id"] in conversation_history:
                messages.extend(conversation_history[session["user_id"]])
            messages.append(Messages(role=MessagesRole.USER, content=user_message))

            payload = Chat(messages=messages)
            response = giga.chat(payload)

            # Сохраняем в историю
            if session["user_id"] not in conversation_history:
                conversation_history[session["user_id"]] = []
            conversation_history[session["user_id"]].append(Messages(role=MessagesRole.USER, content=user_message))
            conversation_history[session["user_id"]].append(Messages(role=MessagesRole.ASSISTANT, content=response.choices[0].message.content))

            return jsonify({"answer": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear_history", methods=["POST"])
def clear_history():
    if "user_id" in session and session["user_id"] in conversation_history:
        conversation_history[session["user_id"]] = []
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
