import json
import os
import random
import sqlite3
import ssl
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# --- 0. НАСТРОЙКИ АДМИНИСТРАЦИИ И СЕРВЕРА ---
# Укажите ваш Telegram ID и ID помощника через запятую:
ADMIN_IDS = [793313971]  # <--- ВСТАВЬТЕ СВАИ ID СЮДА


class HealthCheckHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_check_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_check_server, daemon=True).start()

# --- 1. НАСТРОЙКИ И БАЗА ДАННЫХ ---
TOKEN = "8932170200:AAHpxbAuLChcEkQqaIofxOBUfyN8eVyEvAM"
API_URL = f"https://api.telegram.org/bot{TOKEN}/"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

user_cooldowns = {}
COOLDOWN_TIME = 0.2
user_states = {}

conn = sqlite3.connect("casino.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("PRAGMA journal_mode = WAL;")
cursor.execute("PRAGMA synchronous = NORMAL;")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT,
    balance INTEGER DEFAULT 1000,
    last_bonus INTEGER DEFAULT 0,
    last_ad INTEGER DEFAULT 0,
    job TEXT DEFAULT 'Безработный',
    last_work INTEGER DEFAULT 0,
    spouse_id INTEGER DEFAULT 0,
    last_rob INTEGER DEFAULT 0,
    house TEXT DEFAULT 'Отсутствует',
    car TEXT DEFAULT 'Отсутствует',
    last_rent INTEGER DEFAULT 0,
    bank_balance INTEGER DEFAULT 0,
    deposit_created INTEGER DEFAULT 0,
    deposit_term_days INTEGER DEFAULT 0,
    deposit_rate REAL DEFAULT 0.05,
    last_auto_interest INTEGER DEFAULT 0,
    business TEXT DEFAULT 'Отсутствует',
    last_biz_collect INTEGER DEFAULT 0
)
""")
conn.commit()

for col, col_type in [
    ("last_ad", "INTEGER DEFAULT 0"),
    ("job", "TEXT DEFAULT 'Безработный'"),
    ("last_work", "INTEGER DEFAULT 0"),
    ("spouse_id", "INTEGER DEFAULT 0"),
    ("last_rob", "INTEGER DEFAULT 0"),
    ("house", "TEXT DEFAULT 'Отсутствует'"),
    ("car", "TEXT DEFAULT 'Отсутствует'"),
    ("last_rent", "INTEGER DEFAULT 0"),
    ("bank_balance", "INTEGER DEFAULT 0"),
    ("deposit_created", "INTEGER DEFAULT 0"),
    ("deposit_term_days", "INTEGER DEFAULT 0"),
    ("deposit_rate", "REAL DEFAULT 0.05"),
    ("last_auto_interest", "INTEGER DEFAULT 0"),
    ("business", "TEXT DEFAULT 'Отсутствует'"),
    ("last_biz_collect", "INTEGER DEFAULT 0"),
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def get_user(user_id, first_name="Игрок"):
    cursor.execute(
        "SELECT user_id, first_name, balance, job, spouse_id, house, car, bank_balance, deposit_created, deposit_term_days, deposit_rate, last_auto_interest, business, last_biz_collect FROM users WHERE user_id = ?",
        (user_id,),
    )
    user = cursor.fetchone()
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, first_name, balance) VALUES (?, ?, 1000)",
            (user_id, first_name),
        )
        conn.commit()
        return (
            user_id,
            first_name,
            1000,
            "Безработный",
            0,
            "Отсутствует",
            "Отсутствует",
            0,
            0,
            0,
            0.05,
            0,
            "Отсутствует",
            0,
        )
    return user


def get_user_name(user_id):
    cursor.execute("SELECT first_name FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    return res[0] if res else "Неизвестный"


def update_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id),
    )
    conn.commit()


def process_auto_interest(user_id):
    curr_time = int(time.time())
    cursor.execute(
        "SELECT bank_balance, deposit_created, deposit_rate, last_auto_interest FROM users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return
    bank_bal, dep_created, rate, last_interest = row

    if bank_bal > 0:
        last_check = (
            last_interest
            if last_interest > 0
            else (dep_created if dep_created > 0 else curr_time)
        )
        elapsed_hours = (curr_time - last_check) // 3600

        if elapsed_hours >= 1:
            new_bal = bank_bal
            for _ in range(int(elapsed_hours)):
                new_bal += int(new_bal * rate)

            new_last_interest = last_check + (int(elapsed_hours) * 3600)
            cursor.execute(
                "UPDATE users SET bank_balance = ?, last_auto_interest = ? WHERE user_id = ?",
                (new_bal, new_last_interest, user_id),
            )
            conn.commit()


JOBS = {
    "🏃 Курьер": {"pay": 400, "req": "Доставка еды и посылок"},
    "🚗 Таксист": {"pay": 800, "req": "Перевозка пассажиров"},
    "💻 Программист": {"pay": 2000, "req": "Написание кода и ботов"},
}

HOUSES = {
    "🏠 Уютная квартира": {"price": 5000, "rent": 500},
    "🏡 Загородная вилла": {"price": 25000, "rent": 2500},
    "🏢 Небоскреб": {"price": 100000, "rent": 10000},
}

CARS = {
    "🚗 Жигули": {"price": 2000},
    "🚘 Бизнес-седан": {"price": 12000},
    "🏎 Спорткар": {"price": 50000},
}

BUSINESSES = {
    "⛽️ Автомойка": {"price": 15000, "income": 1200},
    "🍕 Пиццерия": {"price": 60000, "income": 5000},
    "⛏ Майнинг-ферма": {"price": 250000, "income": 22000},
}

games_21 = {}


# --- 2. СЕТЕВАЯ ОТПРАВКА ---
def api_request(method: str, params: dict = None):
    url = API_URL + method
    try:
        data = json.dumps(params).encode("utf-8") if params else None
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(
            req, context=ssl_context, timeout=3
        ) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


def async_send_message(chat_id: int, text: str, reply_markup: dict = None):
    def _worker():
        params = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            params["reply_markup"] = reply_markup
        api_request("sendMessage", params)

    threading.Thread(target=_worker, daemon=True).start()


def async_edit_message_text(
    chat_id: int, message_id: int, text: str, reply_markup: dict = None
):
    def _worker():
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        else:
            params["reply_markup"] = {"inline_keyboard": []}
        api_request("editMessageText", params)

    threading.Thread(target=_worker, daemon=True).start()


def async_answer_callback(callback_id: str, text: str):
    def _worker():
        api_request(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": text, "show_alert": True},
        )

    threading.Thread(target=_worker, daemon=True).start()


# --- 3. КЛАВИАТУРЫ ---
main_bottom_keyboard = {
    "keyboard": [
        [{"text": "📱 Главное меню"}, {"text": "👤 Мой профиль"}],
        [{"text": "🎁 Ежедневный бонус"}, {"text": "ℹ️ Помощь"}],
    ],
    "resize_keyboard": True,
}

main_inline_menu = {
    "inline_keyboard": [
        [
            {"text": "🎰 Казино и Игры", "callback_data": "menu_casino"},
            {"text": "💼 Работа и Заработок", "callback_data": "menu_jobs"},
        ],
        [
            {"text": "🏦 Депозиты и Банк", "callback_data": "menu_bank"},
            {
                "text": "🏰 Недвижимость и Авто",
                "callback_data": "menu_property",
            },
        ],
        [
            {"text": "🏢 Мой Бизнес", "callback_data": "menu_business"},
            {"text": "🏆 Топ богачей", "callback_data": "menu_top"},
        ],
        [{"text": "📺 Реклама (+300$)", "callback_data": "menu_ad"}],
    ]
}

back_to_main_kb = {
    "inline_keyboard": [
        [{"text": "⬅️ Назад в главное меню", "callback_data": "menu_main"}]
    ]
}

casino_menu_keyboard = {
    "inline_keyboard": [
        [{"text": "🎰 Рулетка", "callback_data": "play_roulette_menu"}],
        [{"text": "🃏 Игра 21 (Блэкджек)", "callback_data": "play_21_prompt"}],
        [{"text": "🎲 Кости", "callback_data": "play_dice_prompt"}],
        [{"text": "⬅️ Назад", "callback_data": "menu_main"}],
    ]
}


def get_card():
    return random.choice([2, 3, 4, 6, 7, 8, 9, 10, 11])


def calculate_score(hand):
    score = sum(hand)
    if score > 21 and 11 in hand:
        score -= 10
    return score


def parse_amount(amount_str: str, user_balance: int) -> int:
    amount_str = amount_str.lower().strip()
    if amount_str in ["все", "всё", "all"]:
        return user_balance
    if amount_str.isdigit():
        return int(amount_str)
    return -1


# --- 4. ОСНОВНАЯ ЛОГИКА ---
def handle_update(update: dict):
    user_id = None
    if "message" in update:
        user_id = update["message"]["from"]["id"]
    elif "callback_query" in update:
        user_id = update["callback_query"]["from"]["id"]

    if user_id:
        now = time.time()
        last_time = user_cooldowns.get(user_id, 0)
        if now - last_time < COOLDOWN_TIME:
            return
        user_cooldowns[user_id] = now
        process_auto_interest(user_id)

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        first_name = msg["from"].get("first_name", "Игрок")
        text = msg.get("text", "").strip()
        text_lower = text.lower()

        get_user(user_id, first_name)

        # --- СЕКРЕТНЫЕ АДМИН-КОМАНДЫ (Создатель и Помощник) ---
        if text_lower.startswith(
            ("/givemoney", "/setmoney", "/take", "/setadmin")
        ):
            if user_id not in ADMIN_IDS:
                async_send_message(
                    chat_id,
                    "⛔️ **Отказано в доступе!** Вы не являетесь создателем или помощником бота.",
                )
                return

            parts = text.split()

            # Выдача денег: /givemoney 50000 или через reply
            if text_lower.startswith("/givemoney"):
                if len(parts) >= 2 and parts[1].isdigit():
                    amount = int(parts[1])
                    # Если команда отправлена в ответ на сообщение другого игрока
                    reply_to = msg.get("reply_to_message")
                    target = (
                        reply_to["from"]["id"] if reply_to else user_id
                    )  # если без reply, выдаем себе
                    target_name = (
                        reply_to["from"].get("first_name", "Игрок")
                        if reply_to
                        else "себе"
                    )

                    update_balance(target, amount)
                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** Выдано **+{amount}$** игроку {target_name}!",
                    )
                    return

            # Забрать деньги: /take 50000 (только через reply)
            elif text_lower.startswith("/take"):
                reply_to = msg.get("reply_to_message")
                if reply_to and len(parts) >= 2 and parts[1].isdigit():
                    target = reply_to["from"]["id"]
                    amount = int(parts[1])
                    update_balance(target, -amount)
                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** Изъято **-{amount}$** у игрока {reply_to['from'].get('first_name')}!",
                    )
                    return

        # Обработка ввода сумм
        if user_id in user_states and not text.startswith("/"):
            state = user_states[user_id]
            action = state["action"]

            cursor.execute(
                "SELECT balance, bank_balance FROM users WHERE user_id = ?",
                (user_id,),
            )
            my_balance, bank_balance = cursor.fetchone()

            if action == "bank_deposit_amount":
                amount = parse_amount(text, my_balance)
                del user_states[user_id]
                if amount <= 0 or my_balance < amount:
                    async_send_message(
                        chat_id, "❌ Недостаточно средств или неверная сумма!"
                    )
                    return
                curr_time = int(time.time())
                cursor.execute(
                    "UPDATE users SET balance = balance - ?, bank_balance = bank_balance + ?, deposit_created = ?, deposit_rate = 0.05, last_auto_interest = ? WHERE user_id = ?",
                    (amount, amount, curr_time, curr_time, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    f"🏦 **Депозит пополнен!**\n💵 Внесено: **{amount}$**",
                )
                return

            elif action == "bank_withdraw_amount":
                amount = parse_amount(text, bank_balance)
                del user_states[user_id]
                if amount <= 0 or bank_balance < amount:
                    async_send_message(chat_id, "❌ Недостаточно средств!")
                    return
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, bank_balance = bank_balance - ? WHERE user_id = ?",
                    (amount, amount, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id, f"🏦 Вы успешно сняли с депозита **{amount}$**!"
                )
                return

        # Основные кнопки
        if text.startswith("/start") or text == "📱 Главное меню":
            async_send_message(
                chat_id,
                f"🏰 **RP Мир | Главное меню**\nПриветствуем, {first_name}!",
                reply_markup=main_bottom_keyboard,
            )
            async_send_message(
                chat_id, "👇 Выберите раздел:", reply_markup=main_inline_menu
            )

        elif text in ["👤 Мой профиль", "/profile"]:
            cursor.execute(
                "SELECT balance, job, spouse_id, house, car, bank_balance, business FROM users WHERE user_id = ?",
                (user_id,),
            )
            balance, job, spouse_id, house, car, bank_balance, business = (
                cursor.fetchone()
            )
            spouse_text = (
                f"💍 В браке с: {get_user_name(spouse_id)}"
                if spouse_id
                else "💍 Статус: Холост"
            )

            admin_badge = (
                "👑 **Статус:** Администратор/Создатель\n"
                if user_id in ADMIN_IDS
                else ""
            )

            async_send_message(
                chat_id,
                f"👤 **Ваш RP Профиль:**\n{admin_badge}\n"
                f"📝 Имя: {first_name}\n"
                f"💰 Наличные: **{balance}$**\n"
                f"🏦 В банке: **{bank_balance}$**\n"
                f"💼 Работа: **{job}**\n"
                f"🏢 Бизнес: **{business}**\n"
                f"🏠 Дом: **{house}**\n"
                f"🚗 Авто: **{car}**\n"
                f"{spouse_text}",
            )

        elif text in ["ℹ️ Помощь", "/help"]:
            async_send_message(
                chat_id,
                "📖 **Справочный центр**\n\nИспользуйте меню кнопок под сообщениями для управления персонажем и покупками.",
            )

        elif text == "🎁 Ежедневный бонус":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT last_bonus FROM users WHERE user_id = ?", (user_id,)
            )
            last_bonus = cursor.fetchone()[0]
            if curr_time - last_bonus >= 86400:
                cursor.execute(
                    "UPDATE users SET balance = balance + 500, last_bonus = ? WHERE user_id = ?",
                    (curr_time, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id, "🎉 Вы получили ежедневный бонус **+500$**!"
                )
            else:
                rem = 86400 - (curr_time - last_bonus)
                async_send_message(
                    chat_id,
                    f"⏳ Бонус доступен через: {int(rem // 3600)} ч. {int((rem % 3600) // 60)} мин.",
                )

    elif "callback_query" in update:
        call = update["callback_query"]
        chat_id = call["message"]["chat"]["id"]
        message_id = call["message"]["message_id"]
        data = call.get("data")

        if data == "menu_main":
            async_edit_message_text(
                chat_id,
                message_id,
                "👇 **Главное интерактивное меню:**",
                reply_markup=main_inline_menu,
            )

        elif data == "menu_casino":
            async_edit_message_text(
                chat_id,
                message_id,
                "🎰 **Казино и Азартные Игры**\n\nВыберите игру:",
                reply_markup=casino_menu_keyboard,
            )

        elif data == "menu_business":
            cursor.execute(
                "SELECT business, last_biz_collect FROM users WHERE user_id = ?",
                (user_id,),
            )
            business, last_collect = cursor.fetchone()

            biz_buttons = []
            if business == "Отсутствует":
                for b_name, b_info in BUSINESSES.items():
                    biz_buttons.append([{
                        "text": (
                            f"Купить {b_name} — {b_info['price']}$"
                            f" (+{b_info['income']}$/2ч)"
                        ),
                        "callback_data": f"buy_biz_{b_name}",
                    }])
            else:
                biz_buttons.append([{
                    "text": f"💵 Собрать прибыль с ({business})",
                    "callback_data": "collect_biz",
                }])

            biz_buttons.append(
                [{"text": "⬅️ Назад", "callback_data": "menu_main"}]
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏢 **Управление Бизнесом**\n\nВаш текущий бизнес: **{business}**",
                reply_markup={"inline_keyboard": biz_buttons},
            )

        elif data.startswith("buy_biz_"):
            b_name = data.replace("buy_biz_", "")
            price = BUSINESSES[b_name]["price"]
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = ?", (user_id,)
            )
            balance = cursor.fetchone()[0]

            if balance < price:
                async_answer_callback(
                    call["id"], f"❌ Не хватает {price - balance}$!"
                )
            else:
                cursor.execute(
                    "UPDATE users SET balance = balance - ?, business = ? WHERE user_id = ?",
                    (price, b_name, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"🎉 Куплено: {b_name}!")
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"🎉 Вы успешно купили **{b_name}**!",
                    reply_markup=back_to_main_kb,
                )

        elif data == "collect_biz":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT business, last_biz_collect FROM users WHERE user_id = ?",
                (user_id,),
            )
            business, last_collect = cursor.fetchone()

            if business == "Отсутствует":
                async_answer_callback(call["id"], "❌ У вас нет бизнеса!")
            elif curr_time - last_collect >= 7200:  # раз в 2 часа
                income = BUSINESSES[business]["income"]
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, last_biz_collect = ? WHERE user_id = ?",
                    (income, curr_time, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"💵 Собрано: +{income}$!")
            else:
                rem = 7200 - (curr_time - last_collect)
                async_answer_callback(
                    call["id"],
                    f"⏳ Касса наполняется! До сбора: {int((rem % 3600) // 60)} мин.",
                )

        # Прочие стандартные переходы меню...
        elif data == "menu_bank":
            cursor.execute(
                "SELECT bank_balance, deposit_rate, balance FROM users WHERE"
                " user_id = ?",
                (user_id,),
            )
            bank_balance, dep_rate, my_balance = cursor.fetchone()
            bank_inline_kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "📥 Внести депозит",
                            "callback_data": "bank_dep_prompt",
                        },
                        {
                            "text": "📤 Снять со счета",
                            "callback_data": "bank_wd_prompt",
                        },
                    ],
                    [{"text": "⬅️ Назад", "callback_data": "menu_main"}],
                ]
            }
            async_edit_message_text(
                chat_id,
                message_id,
                f"🏦 **Центральный Банк**\n\n💵 Наличные: **{my_balance}$**\n🏦 На депозите: **{bank_balance}$**",
                reply_markup=bank_inline_kb,
            )

        elif data == "menu_top":
            cursor.execute(
                "SELECT first_name, (balance + bank_balance) as total FROM"
                " users ORDER BY total DESC LIMIT 10"
            )
            top_users = cursor.fetchall()
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            top_text = "🏆 **ТОП-10 САМЫХ БОГАТЫХ ИГРОКОВ** 🏆\n\n"
            for i, (name, total) in enumerate(top_users):
                top_text += f"{medals[i]} {name} — {total}$\n"
            async_edit_message_text(
                chat_id, message_id, top_text, reply_markup=back_to_main_kb
            )


def main():
    api_request("deleteWebhook", {"drop_pending_updates": True})
    print("🚀 Бот запущен!")
    offset = 0
    while True:
        try:
            res = api_request("getUpdates", {"offset": offset, "timeout": 1})
            if res and res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(
                        target=handle_update, args=(update,), daemon=True
                    ).start()
        except Exception as e:
            pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()
