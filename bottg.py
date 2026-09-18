import json
import os
import random
import ssl
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
import psycopg2

# --- 0. НАСТРОЙКИ АДМИНИСТРАЦИИ И СЕРВЕРА ---
ADMIN_USERNAMES = ["stariy_bog1336"]
ADMIN_IDS = [123456789]


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

# --- 1. НАСТРОЙКИ И ПОДКЛЮЧЕНИЕ К ОБЛАЧНОЙ БД (NEON) ---
TOKEN = "8932170200:AAHpxbAuLChcEkQqaIofxOBUfyN8eVyEvAM"
API_URL = f"https://api.telegram.org/bot{TOKEN}/"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

user_cooldowns = {}
COOLDOWN_TIME = 0.2
user_states = {}

# Строка подключения к Neon PostgreSQL
DB_URL = "postgresql://neondb_owner:npg_MZklTNW64pxJ@ep-curly-salad-b4qr5crk-pooler.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"


def get_db_connection():
    return psycopg2.connect(DB_URL)


conn = get_db_connection()
cursor = conn.cursor()

# Создание таблицы в PostgreSQL
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    first_name TEXT,
    balance BIGINT DEFAULT 1000,
    last_bonus BIGINT DEFAULT 0,
    last_ad BIGINT DEFAULT 0,
    job TEXT DEFAULT 'Безработный',
    last_work BIGINT DEFAULT 0,
    spouse_id BIGINT DEFAULT 0,
    last_rob BIGINT DEFAULT 0,
    house TEXT DEFAULT 'Отсутствует',
    car TEXT DEFAULT 'Отсутствует',
    last_rent BIGINT DEFAULT 0,
    bank_balance BIGINT DEFAULT 0,
    deposit_created BIGINT DEFAULT 0,
    deposit_term_days BIGINT DEFAULT 0,
    deposit_rate REAL DEFAULT 0.05,
    last_auto_interest BIGINT DEFAULT 0,
    business TEXT DEFAULT 'Отсутствует',
    last_biz_collect BIGINT DEFAULT 0,
    exp BIGINT DEFAULT 0
)
""")
conn.commit()

# Проверка и добавление колонок для автомиграции
for col, col_type in [
    ("last_ad", "BIGINT DEFAULT 0"),
    ("job", "TEXT DEFAULT 'Безработный'"),
    ("last_work", "BIGINT DEFAULT 0"),
    ("spouse_id", "BIGINT DEFAULT 0"),
    ("last_rob", "BIGINT DEFAULT 0"),
    ("house", "TEXT DEFAULT 'Отсутствует'"),
    ("car", "TEXT DEFAULT 'Отсутствует'"),
    ("last_rent", "BIGINT DEFAULT 0"),
    ("bank_balance", "BIGINT DEFAULT 0"),
    ("deposit_created", "BIGINT DEFAULT 0"),
    ("deposit_term_days", "BIGINT DEFAULT 0"),
    ("deposit_rate", "REAL DEFAULT 0.05"),
    ("last_auto_interest", "BIGINT DEFAULT 0"),
    ("business", "TEXT DEFAULT 'Отсутствует'"),
    ("last_biz_collect", "BIGINT DEFAULT 0"),
    ("exp", "BIGINT DEFAULT 0"),
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        conn.commit()
    except Exception:
        conn.rollback()

# --- ИГРОВЫЕ КАТАЛОГИ ---
JOBS = {
    "Курьер": {"min_exp": 0, "salary": 300},
    "Таксист": {"min_exp": 20, "salary": 800},
    "Программист": {"min_exp": 50, "salary": 2500},
    "Менеджер": {"min_exp": 100, "salary": 6000},
    "Банкир": {"min_exp": 200, "salary": 15000},
    "Депутат": {"min_exp": 500, "salary": 40000},
}

BUSINESSES = {
    "⛽️ Автомойка": {"price": 15000, "income": 1200},
    "🍕 Пиццерия": {"price": 60000, "income": 5000},
    "⛏ Майнинг-ферма": {"price": 250000, "income": 22000},
    "🏨 Отель": {"price": 1000000, "income": 90000},
    "🏢 Бизнес-центр": {"price": 5000000, "income": 450000},
    "🚀 IT-Корпорация": {"price": 25000000, "income": 2000000},
}

CARS = {
    "🚗 ВАЗ 2107": 3000,
    "🚘 Hyundai Accent": 15000,
    "🏎 Toyota Camry 70": 45000,
    "🚙 BMW M5 F90": 120000,
    "🏎 Mercedes-AMG GT": 300000,
    "⚡️ Bugatti Chiron": 1500000,
}

HOUSES = {
    "📦 Комната в общаге": 10000,
    "🏠 Однокомнатная квартира": 50000,
    "🏡 Двухэтажный дом": 200000,
    "🏙 Пентхаус": 800000,
    "🏰 Загородный особняк": 3000000,
    "🏝 Частный остров с виллой": 15000000,
}


def get_user(user_id, first_name="Игрок"):
    cursor.execute(
        "SELECT user_id, first_name, balance, job, spouse_id, house, car,"
        " bank_balance, deposit_created, deposit_term_days, deposit_rate,"
        " last_auto_interest, business, last_biz_collect, exp FROM users WHERE"
        " user_id = %s",
        (user_id,),
    )
    user = cursor.fetchone()
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, first_name, balance) VALUES (%s, %s,"
            " 1000)",
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
            0,
        )
    return user


def get_user_name(user_id):
    cursor.execute(
        "SELECT first_name FROM users WHERE user_id = %s", (user_id,)
    )
    res = cursor.fetchone()
    return res[0] if res else "Неизвестный"


def update_balance(user_id, amount):
    cursor.execute(
        "UPDATE users SET balance = balance + %s WHERE user_id = %s",
        (amount, user_id),
    )
    conn.commit()


def process_auto_interest(user_id):
    curr_time = int(time.time())
    cursor.execute(
        "SELECT bank_balance, deposit_created, deposit_rate, last_auto_interest"
        " FROM users WHERE user_id = %s",
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
                "UPDATE users SET bank_balance = %s, last_auto_interest = %s"
                " WHERE user_id = %s",
                (new_bal, new_last_interest, user_id),
            )
            conn.commit()


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


def async_send_dice(chat_id: int, emoji: str = "🎲"):
    def _worker():
        api_request("sendDice", {"chat_id": chat_id, "emoji": emoji})

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
            {"text": "💼 Работа и Развитие", "callback_data": "menu_jobs"},
        ],
        [
            {"text": "🏦 Банк и Депозиты", "callback_data": "menu_bank"},
            {"text": "🏰 Недвижимость и Авто", "callback_data": "menu_property"},
        ],
        [
            {"text": "🏢 Мой Бизнес", "callback_data": "menu_business"},
            {"text": "🏆 Топ богачей", "callback_data": "menu_top"},
        ],
        [{"text": "📺 Реклама (+300$)", "callback_data": "menu_ad"}],
    ]
}

help_inline_menu = {
    "inline_keyboard": [
        [{"text": "🛠 О разработке и ИИ", "callback_data": "help_dev"}],
        [{"text": "💼 Работа и Заработок", "callback_data": "help_jobs"}],
        [{"text": "🏦 Банк и Депозиты", "callback_data": "help_bank"}],
        [{"text": "🏰 Имущество и Бизнес", "callback_data": "help_property"}],
        [
            {
                "text": "⚔️ Дуэли, Ограбления и Переводы",
                "callback_data": "help_rp",
            }
        ],
        [{"text": "🎰 Казино и Игры", "callback_data": "help_casino"}],
        [{"text": "⬅️ В главное меню", "callback_data": "menu_main"}],
    ]
}

back_to_main_kb = {
    "inline_keyboard": [
        [{"text": "⬅️ Назад в главное меню", "callback_data": "menu_main"}]
    ]
}

casino_menu_keyboard = {
    "inline_keyboard": [
        [
            {
                "text": "🔴 Красное (500$)",
                "callback_data": "cas_roul_red",
            },
            {
                "text": "⚫ Черное (500$)",
                "callback_data": "cas_roul_black",
            },
        ],
        [
            {
                "text": "🎰 Слот-машина (500$ + стикер)",
                "callback_data": "cas_slots_500",
            }
        ],
        [
            {
                "text": "🎲 Кости против бота (1000$ + стикер)",
                "callback_data": "cas_dice_1000",
            }
        ],
        [{"text": "🃏 Блэкджек (21) — 1000$", "callback_data": "cas_bj_start"}],
        [{"text": "⬅️ Назад", "callback_data": "menu_main"}],
    ]
}

bj_game_keyboard = {
    "inline_keyboard": [
        [
            {"text": "🃏 Ещё карту (Hit)", "callback_data": "cas_bj_hit"},
            {"text": "🛑 Хватит (Stand)", "callback_data": "cas_bj_stand"},
        ],
        [{"text": "🚪 Выход в казино", "callback_data": "menu_casino"}],
    ]
}


def is_admin(user_id: int, username: str) -> bool:
    if user_id in ADMIN_IDS:
        return True
    if username and username.lower() in ADMIN_USERNAMES:
        return True
    return False


def parse_amount(amount_str: str, user_balance: int) -> int:
    amount_str = amount_str.lower().strip()
    if amount_str in ["все", "всё", "all"]:
        return user_balance
    if amount_str.isdigit():
        return int(amount_str)
    return -1


# Упрощенное хранение текущей игры в 21 для каждого user_id
blackjack_games = {}


def get_card_val(card):
    if card in ["J", "Q", "K"]:
        return 10
    if card == "A":
        return 11
    return int(card)


def calc_score(hand):
    score = sum(get_card_val(c) for c in hand)
    aces = hand.count("A")
    while score > 21 and aces > 0:
        score -= 10
        aces -= 1
    return score


# --- 4. ОСНОВНАЯ ЛОГИКА ---
def handle_update(update: dict):
    user_id = None
    username = ""
    if "message" in update:
        user_id = update["message"]["from"]["id"]
        username = update["message"]["from"].get("username", "")
    elif "callback_query" in update:
        user_id = update["callback_query"]["from"]["id"]
        username = update["callback_query"]["from"].get("username", "")

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

        # Админ-команды
        if text_lower.startswith(("/givemoney", "/take")):
            if not is_admin(user_id, username):
                async_send_message(
                    chat_id,
                    "⛔️ **Отказано в доступе!** Вы не являетесь администратором"
                    " бота.",
                )
                return

            parts = text.split()
            if text_lower.startswith("/givemoney"):
                if len(parts) >= 2 and parts.isdigit():
                    amount = int(parts)
                    reply_to = msg.get("reply_to_message")
                    target = reply_to["from"]["id"] if reply_to else user_id
                    target_name = (
                        reply_to["from"].get("first_name", "Игрок")
                        if reply_to
                        else "себе"
                    )

                    update_balance(target, amount)
                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** Выдано **+{amount}$**"
                        f" ({target_name})!",
                    )
                    return

            elif text_lower.startswith("/take"):
                reply_to = msg.get("reply_to_message")
                if reply_to and len(parts) >= 2 and parts.isdigit():
                    target = reply_to["from"]["id"]
                    amount = int(parts)
                    update_balance(target, -amount)
                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** Изъято **-{amount}$** у"
                        f" {reply_to['from'].get('first_name')}!",
                    )
                    return

        # ПЕРЕВОД ДЕНЕГ ДРУГОМУ ИГРОКУ: /pay <сумма> в ответ на сообщение
        if text_lower.startswith("/pay"):
            reply_to = msg.get("reply_to_message")
            parts = text.split()
            if not reply_to or len(parts) < 2 or not parts.isdigit():
                async_send_message(
                    chat_id,
                    "ℹ️ **Как переводить:** ответьте на сообщение игрока"
                    " командой `/pay <сумма>` (например, `/pay 1000`).",
                )
                return

            target = reply_to["from"]["id"]
            if target == user_id:
                async_send_message(
                    chat_id, "❌ Нельзя перевести самому себе!"
                )
                return

            amount = int(parts)
            if amount <= 0:
                async_send_message(
                    chat_id, "❌ Сумма должна быть больше нуля!"
                )
                return

            get_user(target, reply_to["from"].get("first_name", "Игрок"))
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            my_bal = cursor.fetchone()[0]

            if my_bal < amount:
                async_send_message(
                    chat_id, "❌ У вас недостаточно наличных для перевода!"
                )
                return

            cursor.execute(
                "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                (amount, user_id),
            )
            cursor.execute(
                "UPDATE users SET balance = balance + %s WHERE user_id = %s",
                (amount, target),
            )
            conn.commit()

            target_name = reply_to["from"].get("first_name", "Игрок")
            async_send_message(
                chat_id,
                f"✅ Вы успешно перевели **{amount}$** игроку **{target_name}**!",
            )
            return

        # ДУЭЛЬ: /duel <ставка> в ответ на сообщение
        if text_lower.startswith("/duel"):
            reply_to = msg.get("reply_to_message")
            parts = text.split()
            if not reply_to or len(parts) < 2 or not parts.isdigit():
                async_send_message(
                    chat_id,
                    "⚔️ **Как дуэлиться:** ответьте на сообщение игрока"
                    " командой `/duel <ставка>` (например, `/duel 500`). Шанс"
                    " победы 50/50.",
                )
                return

            target = reply_to["from"]["id"]
            if target == user_id:
                async_send_message(
                    chat_id, "❌ Нельзя вызвать на дуэль самого себя!"
                )
                return

            stake = int(parts)
            if stake < 100:
                async_send_message(
                    chat_id, "❌ Минимальная ставка для дуэли — 100$!"
                )
                return

            get_user(target, reply_to["from"].get("first_name", "Игрок"))
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            my_bal = cursor.fetchone()[0]
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (target,)
            )
            target_bal = cursor.fetchone()[0]

            if my_bal < stake or target_bal < stake:
                async_send_message(
                    chat_id,
                    "❌ У одного из участников недостаточно средств для такой"
                    " ставки!",
                )
                return

            target_name = reply_to["from"].get("first_name", "Игрок")
            if random.random() < 0.5:
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id = %s",
                    (stake, user_id),
                )
                cursor.execute(
                    "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                    (stake, target),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    f"⚔️ **Дуэль завершена!** Вы победили **{target_name}** и"
                    f" забрали **+{stake}$**!",
                )
            else:
                cursor.execute(
                    "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                    (stake, user_id),
                )
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id = %s",
                    (stake, target),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    f"⚔️ **Дуэль завершена!** Соперник **{target_name}**"
                    f" оказался сильнее, вы проиграли **-{stake}$**.",
                )
            return

        # ОГРАБЛЕНИЕ: /rob в ответ на сообщение
        if text_lower.startswith("/rob"):
            reply_to = msg.get("reply_to_message")
            if not reply_to:
                async_send_message(
                    chat_id,
                    "🕶 **Как грабить:** ответьте на сообщение игрока"
                    " командой `/rob` (кулдаун 15 мин, шанс 40%).",
                )
                return

            target = reply_to["from"]["id"]
            if target == user_id:
                async_send_message(
                    chat_id, "❌ Нельзя ограбить самого себя!"
                )
                return

            curr_time = int(time.time())
            cursor.execute(
                "SELECT last_rob FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            last_rob = row[0] if row else 0

            if curr_time - last_rob < 900:
                rem = 900 - (curr_time - last_rob)
                async_send_message(
                    chat_id,
                    f"⏳ Кулдаун на ограбления: еще {int(rem // 60)} мин.",
                )
                return

            get_user(target, reply_to["from"].get("first_name", "Игрок"))
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (target,)
            )
            target_bal = cursor.fetchone()[0]

            cursor.execute(
                "UPDATE users SET last_rob = %s WHERE user_id = %s",
                (curr_time, user_id),
            )
            conn.commit()

            target_name = reply_to["from"].get("first_name", "Игрок")
            if target_bal < 100:
                async_send_message(
                    chat_id,
                    f"🕶 У **{target_name}** слишком мало наличных в кармане,"
                    " грабить бессмысленно.",
                )
                return

            if random.random() < 0.40:
                loot = min(target_bal, random.randint(150, 1500))
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (loot, user_id),
                )
                cursor.execute(
                    "UPDATE users SET balance = balance - %s WHERE user_id ="
                    " %s",
                    (loot, target),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    f"🕶 **Успешный грабеж!** Вы украли **{loot}$** у"
                    f" **{target_name}**!",
                )
            else:
                fine = random.randint(100, 500)
                cursor.execute(
                    "UPDATE users SET balance = GREATEST(0, balance - %s) WHERE"
                    " user_id = %s",
                    (fine, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    f"🚨 **Полиция пресекла попытку!** Вас поймали при"
                    f" ограблении **{target_name}**, штраф **-{fine}$**.",
                )
            return

        # Ввод сумм для банка
        if user_id in user_states and not text.startswith("/"):
            state = user_states[user_id]
            action = state.get("action")

            cursor.execute(
                "SELECT balance, bank_balance FROM users WHERE user_id = %s",
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
                    "UPDATE users SET balance = balance - %s, bank_balance ="
                    " bank_balance + %s, deposit_created = %s, deposit_rate ="
                    " 0.05, last_auto_interest = %s WHERE user_id = %s",
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
                    "UPDATE users SET balance = balance + %s, bank_balance ="
                    " bank_balance - %s WHERE user_id = %s",
                    (amount, amount, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id, f"🏦 Вы успешно сняли с депозита **{amount}$**!"
                )
                return

        # Текстовые команды
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
                "SELECT balance, job, spouse_id, house, car, bank_balance,"
                " business, exp FROM users WHERE user_id = %s",
                (user_id,),
            )
            (
                balance,
                job,
                spouse_id,
                house,
                car,
                bank_balance,
                business,
                exp,
            ) = cursor.fetchone()
            spouse_text = (
                f"💍 В браке с: {get_user_name(spouse_id)}"
                if spouse_id
                else "💍 Статус: Холост"
            )
            admin_badge = (
                "👑 **Статус:** Владелец / Администратор (@Stariy_bog1336)\n"
                if is_admin(user_id, username)
                else ""
            )

            async_send_message(
                chat_id,
                f"👤 **Ваш RP Профиль:**\n{admin_badge}"
                f"🆔 ID: `{user_id}`\n"
                f"📝 Имя: {first_name}\n"
                f"🔥 Опыт развитости: **{exp} EXP**\n"
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
                "📖 **Справочное бюро**\n\nВыберите нужную категорию из меню ниже:",
                reply_markup=help_inline_menu,
            )

        elif text == "🎁 Ежедневный бонус":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT last_bonus FROM users WHERE user_id = %s", (user_id,)
            )
            last_bonus = cursor.fetchone()[0]
            if curr_time - last_bonus >= 86400:
                cursor.execute(
                    "UPDATE users SET balance = balance + 500, exp = exp + 5,"
                    " last_bonus = %s WHERE user_id = %s",
                    (curr_time, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id,
                    "🎉 Вы получили ежедневный бонус **+500$** и **+5 EXP**!",
                )
            else:
                rem = 86400 - (curr_time - last_bonus)
                async_send_message(
                    chat_id,
                    f"⏳ Бонус доступен через: {int(rem // 3600)} ч."
                    f" {int((rem % 3600) // 60)} мин.",
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

        elif data == "menu_help":
            async_edit_message_text(
                chat_id,
                message_id,
                "📖 **Справочное бюро**\n\nВыберите нужную категорию из меню ниже:",
                reply_markup=help_inline_menu,
            )

        # ПОЛНОЕ ИНТЕРАКТИВНОЕ КАЗИНО (РУЛЕТКА, СЛОТЫ, КОСТИ, 21)
        elif data == "menu_casino":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "🎰 **VIP Казино**\n\n"
                    "Выберите игру:\n"
                    "• 🔴/⚫ Красное/Черное — шанс 50/50, куш x2 (ставка 500$)\n"
                    "• 🎰 Слот-машина — анимационный стикер ТГ (ставка 500$, три"
                    " семерки/одинаковые куш x5)\n"
                    "• 🎲 Кости — анимационный кубик против дилера (ставка"
                    " 1000$)\n"
                    "• 🃏 Блэкджек (21) — классическая карточная игра против"
                    " банка (ставка 1000$)"
                ),
                reply_markup=casino_menu_keyboard,
            )

        elif data in ["cas_roul_red", "cas_roul_black"]:
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            my_bal = row[0] if row else 0
            bet = 500

            if my_bal < bet:
                async_answer_callback(
                    call["id"], f"❌ Нужно минимум {bet}$ на балансе!"
                )
                return

            win = random.choice([True, False])
            color_text = (
                "🔴 Красное" if data == "cas_roul_red" else "⚫ Черное"
            )
            if win:
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (bet, user_id),
                )
                conn.commit()
                async_answer_callback(
                    call["id"],
                    f"🎉 Выпал правильный сектор! Вы выиграли +{bet}$!",
                )
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"🎰 **Рулетка ({color_text})**\n🎉 **Победа!** Вы забрали"
                    f" **+{bet}$**!",
                    reply_markup=back_to_main_kb,
                )
            else:
                cursor.execute(
                    "UPDATE users SET balance = balance - %s WHERE user_id ="
                    " %s",
                    (bet, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"😢 Промах, -{bet}$")
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"🎰 **Рулетка ({color_text})**\n😢 **Проигрыш** —{bet}$."
                    " Фортуна отвернулась.",
                    reply_markup=back_to_main_kb,
                )

        elif data == "cas_slots_500":
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            my_bal = row[0] if row else 0
            bet = 500

            if my_bal < bet:
                async_answer_callback(
                    call["id"], f"❌ Нужно минимум {bet}$ на балансе!"
                )
                return

            # Списываем ставку перед броском
            cursor.execute(
                "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                (bet, user_id),
            )
            conn.commit()

            # Отправляем анимационный стикер ТГ слотов
            async_send_dice(chat_id, "🎰")

            # Симуляция выпадения результата слотов (Telegram slots values 1-64, 22/43/64 - джекпот/комбо)
            slot_win = random.random() < 0.35  # 35% шанс победы
            if slot_win:
                payout = bet * 3
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (payout, user_id),
                )
                conn.commit()
                async_answer_callback(
                    call["id"], f"🎰 ДЖЕКПОТ! Выиграно +{payout}$!"
                )
            else:
                async_answer_callback(
                    call["id"], f"🎰 Комбинация мимо, -{bet}$"
                )

        elif data == "cas_dice_1000":
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            my_bal = row[0] if row else 0
            bet = 1000

            if my_bal < bet:
                async_answer_callback(
                    call["id"], f"❌ Нужно минимум {bet}$ на балансе!"
                )
                return

            cursor.execute(
                "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                (bet, user_id),
            )
            conn.commit()

            # Кидаем анимационный кубик в чат от имени бота / игрока
            async_send_dice(chat_id, "🎲")

            my_dice = random.randint(1, 6)
            bot_dice = random.randint(1, 6)

            if my_dice > bot_dice:
                win_amt = bet * 2
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (win_amt, user_id),
                )
                conn.commit()
                async_answer_callback(
                    call["id"],
                    f"🎲 У вас {my_dice}, у бота {bot_dice}. Выиграли"
                    f" +{win_amt}$!",
                )
            elif my_dice < bot_dice:
                async_answer_callback(
                    call["id"],
                    f"🎲 У вас {my_dice}, у бота {bot_dice}. Проигрыш"
                    f" -{bet}$!",
                )
            else:
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (bet, user_id),
                )
                conn.commit()
                async_answer_callback(
                    call["id"],
                    f"🎲 Ничья ({my_dice}:{bot_dice}), ставка возвращена.",
                )

        # БЛЭКДЖЕК (21)
        elif data == "cas_bj_start":
            cursor.execute(
                "SELECT balance FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            my_bal = row[0] if row else 0
            bet = 1000

            if my_bal < bet:
                async_answer_callback(
                    call["id"], f"❌ Нужно минимум {bet}$ для игры в 21!"
                )
                return

            cursor.execute(
                "UPDATE users SET balance = balance - %s WHERE user_id = %s",
                (bet, user_id),
            )
            conn.commit()

            deck = [
                "2",
                "3",
                "4",
                "5",
                "6",
                "7",
                "8",
                "9",
                "10",
                "J",
                "Q",
                "K",
                "A",
            ] * 4
            random.shuffle(deck)

            player_hand = [deck.pop(), deck.pop()]
            dealer_hand = [deck.pop(), deck.pop()]

            blackjack_games[user_id] = {
                "deck": deck,
                "player": player_hand,
                "dealer": dealer_hand,
                "bet": bet,
            }

            p_score = calc_score(player_hand)
            async_edit_message_text(
                chat_id,
                message_id,
                f"🃏 **Блэкджек (21)**\n"
                f"Ваши карты: `{' '.join(player_hand)}` (Счет: **{p_score}**)\n"
                f"Карта дилера: `{dealer_hand[0]}` [скрыта]\n\n"
                f"Ваш ход:",
                reply_markup=bj_game_keyboard,
            )

        elif data == "cas_bj_hit":
            game = blackjack_games.get(user_id)
            if not game:
                async_answer_callback(
                    call["id"], "❌ Активная игра не найдена!"
                )
                return

            game["player"].append(game["deck"].pop())
            p_score = calc_score(game["player"])

            if p_score > 21:
                del blackjack_games[user_id]
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"🃏 **Блэкджек (21)**\n"
                    f"Ваши карты: `{' '.join(game['player'])}` (Счет: **перебор"
                    f" {p_score}**)\n\n"
                    f"😢 **Вы перебрали и проиграли ставку (-{game['bet']}$)!**",
                    reply_markup=back_to_main_kb,
                )
            else:
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"🃏 **Блэкджек (21)**\n"
                    f"Ваши карты: `{' '.join(game['player'])}` (Счет:"
                    f" **{p_score}**)\n"
                    f"Карта дилера: `{game['dealer'][0]}` [скрыта]\n\n"
                    f"Ваш ход:",
                    reply_markup=bj_game_keyboard,
                )

        elif data == "cas_bj_stand":
            game = blackjack_games.pop(user_id, None)
            if not game:
                async_answer_callback(
                    call["id"], "❌ Активная игра не найдена!"
                )
                return

            p_score = calc_score(game["player"])
            d_score = calc_score(game["dealer"])

            while d_score < 17:
                game["dealer"].append(game["deck"].pop())
                d_score = calc_score(game["dealer"])

            res_text = (
                f"🃏 **Итоги Блэкджека**\n"
                f"Ваши карты: `{' '.join(game['player'])}` (Счет:"
                f" **{p_score}**)\n"
                f"Карты дилера: `{' '.join(game['dealer'])}` (Счет:"
                f" **{d_score}**)\n\n"
            )

            bet = game["bet"]
            if d_score > 21 or p_score > d_score:
                win_amt = bet * 2
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (win_amt, user_id),
                )
                conn.commit()
                res_text += f"🎉 **Победа! Вы выиграли +{win_amt}$!**"
            elif p_score < d_score:
                res_text += f"😢 **Дилер выиграл, вы проиграли -{bet}$!**"
            else:
                cursor.execute(
                    "UPDATE users SET balance = balance + %s WHERE user_id ="
                    " %s",
                    (bet, user_id),
                )
                conn.commit()
                res_text += f"🤝 **Ничья! Ставка возвращена (+{bet}$)**"

            async_edit_message_text(
                chat_id, message_id, res_text, reply_markup=back_to_main_kb
            )

        # РАБОТА И РАЗВИТИЕ
        elif data == "menu_jobs":
            cursor.execute(
                "SELECT job, last_work, exp FROM users WHERE user_id = %s",
                (user_id,),
            )
            job, last_work, exp = cursor.fetchone()

            job_buttons = []
            for j_name, j_info in JOBS.items():
                job_buttons.append([{
                    "text": (
                        f"{'✅ ' if job == j_name else ''}{j_name} —"
                        f" {j_info['salary']}$ (требуется {j_info['min_exp']}"
                        " EXP)"
                    ),
                    "callback_data": f"set_job_{j_name}",
                }])

            job_buttons.append([
                {
                    "text": "⚒ Отработать смену (+Доход & EXP)",
                    "callback_data": "do_work",
                }
            ])
            job_buttons.append(
                [{"text": "⬅️ Назад", "callback_data": "menu_main"}]
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"💼 **Центр Трудоустройства**\n\n"
                f"Ваш текущий опыт: **{exp} EXP**\n"
                f"Ваша профессия: **{job}**\n\n"
                f"Чем выше ваш опыт и должность, тем больше вы зарабатываете!",
                reply_markup={"inline_keyboard": job_buttons},
            )

        elif data.startswith("set_job_"):
            j_name = data.replace("set_job_", "")
            if j_name in JOBS:
                cursor.execute(
                    "SELECT exp FROM users WHERE user_id = %s", (user_id,)
                )
                user_exp = cursor.fetchone()[0]

                if user_exp < JOBS[j_name]["min_exp"]:
                    async_answer_callback(
                        call["id"],
                        f"❌ Не хватает опыта! Требуется"
                        f" {JOBS[j_name]['min_exp']} EXP.",
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET job = %s WHERE user_id = %s",
                        (j_name, user_id),
                    )
                    conn.commit()
                    async_answer_callback(
                        call["id"], f"🎉 Вы устроились: {j_name}!"
                    )
                    async_edit_message_text(
                        chat_id,
                        message_id,
                        f"🎉 Вы успешно устроились на работу: **{j_name}**!",
                        reply_markup=back_to_main_kb,
                    )

        elif data == "do_work":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT job, last_work, exp FROM users WHERE user_id = %s",
                (user_id,),
            )
            job, last_work, exp = cursor.fetchone()

            if job == "Безработный":
                async_answer_callback(
                    call["id"], "❌ Выберите профессию в списке!"
                )
            elif curr_time - last_work >= 600:
                salary = JOBS[job]["salary"] + (exp * 2)
                cursor.execute(
                    "UPDATE users SET balance = balance + %s, exp = exp + 10,"
                    " last_work = %s WHERE user_id = %s",
                    (salary, curr_time, user_id),
                )
                conn.commit()
                async_answer_callback(
                    call["id"], f"💰 Заработано: +{salary}$ и +10 EXP!"
                )
            else:
                rem = 600 - (curr_time - last_work)
                async_answer_callback(
                    call["id"], f"⏳ Отдых еще: {int(rem // 60)} мин. {rem % 60} сек."
                )

        # НЕДВИЖИМОСТЬ И АВТО
        elif data == "menu_property":
            cursor.execute(
                "SELECT house, car FROM users WHERE user_id = %s", (user_id,)
            )
            house, car = cursor.fetchone()

            prop_buttons = [
                [{"text": "🚗 Купить Автомобиль", "callback_data": "buy_car_menu"}],
                [{"text": "🏠 Купить Недвижимость", "callback_data": "buy_house_menu"}],
                [{"text": "⬅️ Назад", "callback_data": "menu_main"}],
            ]

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏰 **Рынок Имущества**\n\n"
                f"🏠 Ваш дом: **{house}**\n"
                f"🚗 Ваше авто: **{car}**\n\n"
                f"Выберите категорию для покупки:",
                reply_markup={"inline_keyboard": prop_buttons},
            )

        elif data == "buy_car_menu":
            car_buttons = []
            for c_name, c_price in CARS.items():
                car_buttons.append([{
                    "text": f"{c_name} — {c_price}$",
                    "callback_data": f"buycar_{c_name}",
                }])
            car_buttons.append(
                [{"text": "⬅️ Назад", "callback_data": "menu_property"}]
            )

            async_edit_message_text(
                chat_id,
                message_id,
                "🚗 **Автосалон**\nВыберите машину для покупки:",
                reply_markup={"inline_keyboard": car_buttons},
            )

        elif data.startswith("buycar_"):
            c_name = data.replace("buycar_", "")
            if c_name in CARS:
                price = CARS[c_name]
                cursor.execute(
                    "SELECT balance FROM users WHERE user_id = %s", (user_id,)
                )
                balance = cursor.fetchone()[0]

                if balance < price:
                    async_answer_callback(
                        call["id"], f"❌ Не хватает {price - balance}$!"
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET balance = balance - %s, car = %s"
                        " WHERE user_id = %s",
                        (price, c_name, user_id),
                    )
                    conn.commit()
                    async_answer_callback(call["id"], f"🏎 Куплено: {c_name}!")
                    async_edit_message_text(
                        chat_id,
                        message_id,
                        f"🏎 Поздравляем с покупкой авто **{c_name}**!",
                        reply_markup=back_to_main_kb,
                    )

        elif data == "buy_house_menu":
            house_buttons = []
            for h_name, h_price in HOUSES.items():
                house_buttons.append([{
                    "text": f"{h_name} — {h_price}$",
                    "callback_data": f"buyhouse_{h_name}",
                }])
            house_buttons.append(
                [{"text": "⬅️ Назад", "callback_data": "menu_property"}]
            )

            async_edit_message_text(
                chat_id,
                message_id,
                "🏠 **Агентство Недвижимости**\nВыберите жилье для покупки:",
                reply_markup={"inline_keyboard": house_buttons},
            )

        elif data.startswith("buyhouse_"):
            h_name = data.replace("buyhouse_", "")
            if h_name in HOUSES:
                price = HOUSES[h_name]
                cursor.execute(
                    "SELECT balance FROM users WHERE user_id = %s", (user_id,)
                )
                balance = cursor.fetchone()[0]

                if balance < price:
                    async_answer_callback(
                        call["id"], f"❌ Не хватает {price - balance}$!"
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET balance = balance - %s, house = %s"
                        " WHERE user_id = %s",
                        (price, h_name, user_id),
                    )
                    conn.commit()
                    async_answer_callback(call["id"], f"🏠 Куплено: {h_name}!")
                    async_edit_message_text(
                        chat_id,
                        message_id,
                        f"🏠 Поздравляем с покупкой жилья **{h_name}**!",
                        reply_markup=back_to_main_kb,
                    )

        # БАНК
        elif data == "menu_bank":
            cursor.execute(
                "SELECT bank_balance, deposit_rate, balance FROM users WHERE"
                " user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            bank_balance = row[0] if row else 0
            my_balance = row if row else 0

            bank_inline_kb = {
                "inline_keyboard": [
                    [
                        {
                            "text": "📥 Внести на депозит",
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
                f"🏦 **Центральный Банк**\n\n"
                f"💵 Наличные: **{my_balance}$**\n"
                f"🏦 На депозите: **{bank_balance}$**\n"
                f"📈 Начисление: **5% в час** (автоматически)",
                reply_markup=bank_inline_kb,
            )

        elif data == "bank_dep_prompt":
            user_states[user_id] = {"action": "bank_deposit_amount"}
            async_send_message(
                chat_id,
                "📥 **Пополнение депозита**\nВведите сумму, которую хотите"
                " положить в банк (или напишите `все`):",
            )

        elif data == "bank_wd_prompt":
            user_states[user_id] = {"action": "bank_withdraw_amount"}
            async_send_message(
                chat_id,
                "📤 **Снятие с депозита**\nВведите сумму, которую хотите снять"
                " из банка (или напишите `все`):",
            )

        # БИЗНЕС
        elif data == "menu_business":
            cursor.execute(
                "SELECT business, last_biz_collect FROM users WHERE user_id ="
                " %s",
                (user_id,),
            )
            row = cursor.fetchone()
            business = row[0] if row else "Отсутствует"

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
                    "text": f"💵 Собрать прибыль ({business})",
                    "callback_data": "collect_biz",
                }])

            biz_buttons.append(
                [{"text": "⬅️ Назад", "callback_data": "menu_main"}]
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏢 **Управление Бизнесом**\n\nВаш текущий бизнес:"
                f" **{business}**",
                reply_markup={"inline_keyboard": biz_buttons},
            )

        elif data.startswith("buy_biz_"):
            b_name = data.replace("buy_biz_", "")
            if b_name in BUSINESSES:
                price = BUSINESSES[b_name]["price"]
                cursor.execute(
                    "SELECT balance FROM users WHERE user_id = %s", (user_id,)
                )
                balance = cursor.fetchone()[0]

                if balance < price:
                    async_answer_callback(
                        call["id"], f"❌ Не хватает {price - balance}$!"
                    )
                else:
                    cursor.execute(
                        "UPDATE users SET balance = balance - %s, business = %s"
                        " WHERE user_id = %s",
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
                "SELECT business, last_biz_collect, exp FROM users WHERE user_id"
                " = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            business = row[0] if row else "Отсутствует"
            last_collect = row if row else 0
            exp = row if row else 0

            if business == "Отсутствует":
                async_answer_callback(call["id"], "❌ У вас нет бизнеса!")
            elif curr_time - last_collect >= 7200:
                income = BUSINESSES[business]["income"] + (exp * 10)
                cursor.execute(
                    "UPDATE users SET balance = balance + %s,"
                    " last_biz_collect = %s WHERE user_id = %s",
                    (income, curr_time, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"💵 Собрано: +{income}$!")
            else:
                rem = 7200 - (curr_time - last_collect)
                async_answer_callback(
                    call["id"],
                    f"⏳ До сбора кассы: {int((rem % 3600) // 60)} мин.",
                )

        # РАСШИРЕННЫЕ КАТЕГОРИИ ПОМОЩИ
        elif data == "help_dev":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "🛠 **О разработке и ИИ**\n\n"
                    "• Бот создан на Python + PostgreSQL (Neon).\n"
                    "• Архитектура: потоковый асинхронный polling + HTTP-health"
                    " check для Render.\n"
                    "• Администратор и владелец: **@Stariy_bog1336**"
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "help_jobs":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "💼 **Работа и Заработок**\n\n"
                    "• Устраивайтесь на работу через меню (`💼 Работа и"
                    " Развитие`).\n"
                    "• Опыт (EXP) растет за каждую смену (+10 EXP) и за"
                    " ежедневный бонус (+5 EXP).\n"
                    "• Больше опыта = выше зарплата и бонус к доходу с"
                    " бизнеса."
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "help_bank":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "🏦 **Банк и Депозиты**\n\n"
                    "• Пополняйте счет наличными.\n"
                    "• На депозит автоматически начисляется **5% в час**"
                    " при любом обращении к боту."
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "help_property":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "🏰 **Имущество и Бизнес**\n\n"
                    "• Покупайте машины (6 уровней) и дома (6 уровней) для"
                    " статуса в профиле.\n"
                    "• Покупайте бизнесы (Автомойка, Пиццерия, Ферма, Отель,"
                    " БЦ, IT-Корпорация) для пассивного дохода раз в 2 часа."
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "help_rp":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "⚔️ **Дуэли, Ограбления и Переводы**\n\n"
                    "• **Перевод:** ответьте `/pay <сумма>` на сообщение"
                    " игрока.\n"
                    "• **Дуэль:** ответьте `/duel <ставка>` на сообщение"
                    " игрока (шанс 50/50).\n"
                    "• **Ограбление:** ответьте `/rob` на сообщение игрока"
                    " (кулдаун 15 мин, шанс 40%)."
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "help_casino":
            async_edit_message_text(
                chat_id,
                message_id,
                (
                    "🎰 **Казино и Игры**\n\n"
                    "• Играйте в Красное/Черное, анимационные слоты (`🎰`),"
                    " кости против бота (`🎲`) или карточный блэкджек (21)."
                ),
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "⬅️ Назад", "callback_data": "menu_help"}]
                    ]
                },
            )

        elif data == "menu_ad":
            cursor.execute(
                "SELECT last_ad FROM users WHERE user_id = %s", (user_id,)
            )
            row = cursor.fetchone()
            last_ad = row[0] if row else 0
            curr_time = int(time.time())
                    if curr_time - last_ad >= 1800:
            cursor.execute(
                "UPDATE users SET balance = balance + 300, last_ad = %s WHERE"
                " user_id = %s",
                (curr_time, user_id),
            )
            conn.commit()
            async_answer_callback(
                call["id"], "📺 Начислено +300$ за просмотр рекламы!"
            )
        else:
            rem = 1800 - (curr_time - last_ad)
            async_answer_callback(
                call["id"], f"⏳ Доступно через: {int(rem // 60)} мин."
            )

    elif data == "menu_top":
        cursor.execute(
            "SELECT first_name, (balance + bank_balance) as total FROM users"
            " ORDER BY total DESC LIMIT 10"
        )
        top_users = cursor.fetchall()
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        top_text = "🏆 **ТОП-10 САМЫХ БОГАТЫХ ИГРОКОВ** 🏆\n\n"
        for i, (name, total) in enumerate(top_users):
            if i < len(medals):
                top_text += f"{medals[i]} {name} — {total}$\n"
        async_edit_message_text(
            chat_id, message_id, top_text, reply_markup=back_to_main_kb
        )



def main():
    api_request("deleteWebhook", {"drop_pending_updates": True})
    print("🚀 Бот запущен с полным интерактивным казино и PostgreSQL (Neon)!")
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
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()

