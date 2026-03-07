import os
from flask import Flask, request, jsonify, render_template
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

app = Flask(__name__)

# Проверяем, что ключ API загружен
GIGACHAT_CREDENTIALS = os.getenv("GIGACHAT_CREDENTIALS")
if not GIGACHAT_CREDENTIALS:
    raise ValueError("Не найден ключ API для GigaChat. Установите переменную окружения GIGACHAT_CREDENTIALS.")

# История сообщений
conversation_history = []

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask_gigachat():
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
        global conversation_history
        conversation_history = []
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

            for msg in conversation_history:
                messages.append(msg)

            messages.append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )

            payload = Chat(messages=messages)
            response = giga.chat(payload)

            conversation_history.append(
                Messages(
                    role=MessagesRole.USER,
                    content=user_message
                )
            )
            conversation_history.append(
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
    global conversation_history
    conversation_history = []
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
