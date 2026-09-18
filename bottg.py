import json
import os
import random
import ssl
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2


# =========================
# 0. НАСТРОЙКИ
# =========================

ADMIN_USERNAMES = ["stariy_bog1336"]
ADMIN_IDS = [123456789]

TOKEN = os.environ.get("8932170200:AAHpxbAuLChcEkQqaIofxOBUfyN8eVyEvAM")
DB_URL = os.environ.get("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("Не задана переменная окружения BOT_TOKEN")

if not DB_URL:
    raise RuntimeError("Не задана переменная окружения DATABASE_URL")

API_URL = f"https://api.telegram.org/bot{TOKEN}/"

COOLDOWN_TIME = 0.2

user_cooldowns = {}
user_states = {}
blackjack_games = {}


# =========================
# HEALTH CHECK SERVER
# =========================

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


threading.Thread(
    target=run_health_check_server,
    daemon=True
).start()


# =========================
# SSL
# =========================

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


# =========================
# DATABASE
# =========================

def get_db_connection():
    return psycopg2.connect(DB_URL)


conn = get_db_connection()
cursor = conn.cursor()


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


# Автомиграция старых таблиц
MIGRATION_COLUMNS = [
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
]


for column, column_type in MIGRATION_COLUMNS:
    try:
        cursor.execute(
            f"ALTER TABLE users ADD COLUMN {column} {column_type}"
        )
        conn.commit()
    except Exception:
        conn.rollback()


# =========================
# ИГРОВЫЕ КАТАЛОГИ
# =========================

JOBS = {
    "Курьер": {
        "min_exp": 0,
        "salary": 300
    },
    "Таксист": {
        "min_exp": 20,
        "salary": 800
    },
    "Программист": {
        "min_exp": 50,
        "salary": 2500
    },
    "Менеджер": {
        "min_exp": 100,
        "salary": 6000
    },
    "Банкир": {
        "min_exp": 200,
        "salary": 15000
    },
    "Депутат": {
        "min_exp": 500,
        "salary": 40000
    },
}


BUSINESSES = {
    "⛽️ Автомойка": {
        "price": 15000,
        "income": 1200
    },
    "🍕 Пиццерия": {
        "price": 60000,
        "income": 5000
    },
    "⛏ Майнинг-ферма": {
        "price": 250000,
        "income": 22000
    },
    "🏨 Отель": {
        "price": 1000000,
        "income": 90000
    },
    "🏢 Бизнес-центр": {
        "price": 5000000,
        "income": 450000
    },
    "🚀 IT-Корпорация": {
        "price": 25000000,
        "income": 2000000
    },
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


# =========================
# USERS
# =========================

def get_user(user_id, first_name="Игрок"):
    cursor.execute(
        """
        SELECT
            user_id,
            first_name,
            balance,
            job,
            spouse_id,
            house,
            car,
            bank_balance,
            deposit_created,
            deposit_term_days,
            deposit_rate,
            last_auto_interest,
            business,
            last_biz_collect,
            exp
        FROM users
        WHERE user_id = %s
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        cursor.execute(
            """
            INSERT INTO users (
                user_id,
                first_name,
                balance
            )
            VALUES (%s, %s, %s)
            """,
            (user_id, first_name, 1000)
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
            0
        )

    return user


def get_user_name(user_id):
    cursor.execute(
        "SELECT first_name FROM users WHERE user_id = %s",
        (user_id,)
    )

    result = cursor.fetchone()

    return result[0] if result else "Неизвестный"


def update_balance(user_id, amount):
    cursor.execute(
        """
        UPDATE users
        SET balance = balance + %s
        WHERE user_id = %s
        """,
        (amount, user_id)
    )

    conn.commit()


# =========================
# BANK INTEREST
# =========================

def process_auto_interest(user_id):
    current_time = int(time.time())

    cursor.execute(
        """
        SELECT
            bank_balance,
            deposit_created,
            deposit_rate,
            last_auto_interest
        FROM users
        WHERE user_id = %s
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    if not row:
        return

    bank_balance, deposit_created, rate, last_interest = row

    if bank_balance <= 0:
        return

    last_check = (
        last_interest
        if last_interest > 0
        else (
            deposit_created
            if deposit_created > 0
            else current_time
        )
    )

    elapsed_hours = (current_time - last_check) // 3600

    if elapsed_hours < 1:
        return

    new_balance = bank_balance

    for _ in range(int(elapsed_hours)):
        new_balance += int(new_balance * rate)

    new_last_interest = (
        last_check + int(elapsed_hours) * 3600
    )

    cursor.execute(
        """
        UPDATE users
        SET
            bank_balance = %s,
            last_auto_interest = %s
        WHERE user_id = %s
        """,
        (
            new_balance,
            new_last_interest,
            user_id
        )
    )

    conn.commit()


# =========================
# TELEGRAM API
# =========================

def api_request(method: str, params: dict = None):
    url = API_URL + method

    try:
        data = (
            json.dumps(params).encode("utf-8")
            if params
            else None
        )

        headers = {
            "Content-Type": "application/json"
        }

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers
        )

        with urllib.request.urlopen(
            request,
            context=ssl_context,
            timeout=5
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except Exception as error:
        return {
            "ok": False,
            "error": str(error)
        }


def async_send_message(
    chat_id: int,
    text: str,
    reply_markup: dict = None
):
    def worker():
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        if reply_markup:
            params["reply_markup"] = reply_markup

        api_request(
            "sendMessage",
            params
        )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


def async_send_dice(
    chat_id: int,
    emoji: str = "🎲"
):
    def worker():
        api_request(
            "sendDice",
            {
                "chat_id": chat_id,
                "emoji": emoji
            }
        )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


def async_edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: dict = None
):
    def worker():
        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }

        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        else:
            params["reply_markup"] = {
                "inline_keyboard": []
            }

        api_request(
            "editMessageText",
            params
        )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


def async_answer_callback(
    callback_id: str,
    text: str
):
    def worker():
        api_request(
            "answerCallbackQuery",
            {
                "callback_query_id": callback_id,
                "text": text,
                "show_alert": True
            }
        )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


# =========================
# KEYBOARDS
# =========================

main_bottom_keyboard = {
    "keyboard": [
        [
            {"text": "📱 Главное меню"},
            {"text": "👤 Мой профиль"}
        ],
        [
            {"text": "🎁 Ежедневный бонус"},
            {"text": "ℹ️ Помощь"}
        ]
    ],
    "resize_keyboard": True
}


main_inline_menu = {
    "inline_keyboard": [
        [
            {
                "text": "🎰 Казино и Игры",
                "callback_data": "menu_casino"
            },
            {
                "text": "💼 Работа и Развитие",
                "callback_data": "menu_jobs"
            }
        ],
        [
            {
                "text": "🏦 Банк и Депозиты",
                "callback_data": "menu_bank"
            },
            {
                "text": "🏰 Недвижимость и Авто",
                "callback_data": "menu_property"
            }
        ],
        [
            {
                "text": "🏢 Мой Бизнес",
                "callback_data": "menu_business"
            },
            {
                "text": "🏆 Топ богачей",
                "callback_data": "menu_top"
            }
        ],
        [
            {
                "text": "📺 Реклама (+300$)",
                "callback_data": "menu_ad"
            }
        ]
    ]
}


help_inline_menu = {
    "inline_keyboard": [
        [
            {
                "text": "🛠 О разработке и ИИ",
                "callback_data": "help_dev"
            }
        ],
        [
            {
                "text": "💼 Работа и Заработок",
                "callback_data": "help_jobs"
            }
        ],
        [
            {
                "text": "🏦 Банк и Депозиты",
                "callback_data": "help_bank"
            }
        ],
        [
            {
                "text": "🏰 Имущество и Бизнес",
                "callback_data": "help_property"
            }
        ],
        [
            {
                "text": "⚔️ Дуэли, Ограбления и Переводы",
                "callback_data": "help_rp"
            }
        ],
        [
            {
                "text": "🎰 Казино и Игры",
                "callback_data": "help_casino"
            }
        ],
        [
            {
                "text": "⬅️ В главное меню",
                "callback_data": "menu_main"
            }
        ]
    ]
}


back_to_main_kb = {
    "inline_keyboard": [
        [
            {
                "text": "⬅️ Назад в главное меню",
                "callback_data": "menu_main"
            }
        ]
    ]
}


casino_menu_keyboard = {
    "inline_keyboard": [
        [
            {
                "text": "🔴 Красное (500$)",
                "callback_data": "cas_roul_red"
            },
            {
                "text": "⚫ Черное (500$)",
                "callback_data": "cas_roul_black"
            }
        ],
        [
            {
                "text": "🎰 Слот-машина (500$ + стикер)",
                "callback_data": "cas_slots_500"
            }
        ],
        [
            {
                "text": "🎲 Кости против бота (1000$ + стикер)",
                "callback_data": "cas_dice_1000"
            }
        ],
        [
            {
                "text": "🃏 Блэкджек (21) — 1000$",
                "callback_data": "cas_bj_start"
            }
        ],
        [
            {
                "text": "⬅️ Назад",
                "callback_data": "menu_main"
            }
        ]
    ]
}


bj_game_keyboard = {
    "inline_keyboard": [
        [
            {
                "text": "🃏 Ещё карту (Hit)",
                "callback_data": "cas_bj_hit"
            },
            {
                "text": "🛑 Хватит (Stand)",
                "callback_data": "cas_bj_stand"
            }
        ],
        [
            {
                "text": "🚪 Выход в казино",
                "callback_data": "menu_casino"
            }
        ]
    ]
}


# =========================
# HELPERS
# =========================

def is_admin(
    user_id: int,
    username: str
) -> bool:
    if user_id in ADMIN_IDS:
        return True

    if username:
        return username.lower() in [
            name.lower()
            for name in ADMIN_USERNAMES
        ]

    return False


def parse_amount(
    amount_str: str,
    user_balance: int
) -> int:
    amount_str = amount_str.lower().strip()

    if amount_str in ["все", "всё", "all"]:
        return user_balance

    if amount_str.isdigit():
        return int(amount_str)

    return -1


def get_user_balance(user_id):
    cursor.execute(
        "SELECT balance FROM users WHERE user_id = %s",
        (user_id,)
    )

    row = cursor.fetchone()

    return row[0] if row else 0


def get_callback_user(update):
    callback = update.get("callback_query")

    if not callback:
        return None

    return callback.get("from", {})


# =========================
# BLACKJACK
# =========================

def get_card_val(card):
    if card in ["J", "Q", "K"]:
        return 10

    if card == "A":
        return 11

    return int(card)


def calc_score(hand):
    score = sum(
        get_card_val(card)
        for card in hand
    )

    aces = hand.count("A")

    while score > 21 and aces > 0:
        score -= 10
        aces -= 1

    return score


# =========================
# MAIN UPDATE HANDLER
# =========================

def handle_update(update: dict):
    user_id = None
    username = ""

    if "message" in update:
        user_from = update["message"].get("from", {})
        user_id = user_from.get("id")
        username = user_from.get("username", "")

    elif "callback_query" in update:
        user_from = update["callback_query"].get("from", {})
        user_id = user_from.get("id")
        username = user_from.get("username", "")

    if user_id:
        now = time.time()
        last_time = user_cooldowns.get(
            user_id,
            0
        )

        if now - last_time < COOLDOWN_TIME:
            return

        user_cooldowns[user_id] = now

        get_user(
            user_id,
            user_from.get("first_name", "Игрок")
        )

        process_auto_interest(user_id)

    # =========================
    # MESSAGE
    # =========================

    if "message" in update:
        msg = update["message"]

        chat_id = msg["chat"]["id"]

        first_name = msg["from"].get(
            "first_name",
            "Игрок"
        )

        text = msg.get(
            "text",
            ""
        ).strip()

        text_lower = text.lower()

        get_user(
            user_id,
            first_name
        )

        # =========================
        # ADMIN COMMANDS
        # =========================

        if text_lower.startswith(
            ("/givemoney", "/take")
        ):
            if not is_admin(
                user_id,
                username
            ):
                async_send_message(
                    chat_id,
                    "⛔️ **Отказано в доступе!** "
                    "Вы не являетесь администратором бота."
                )
                return

            parts = text.split()

            if text_lower.startswith("/givemoney"):
                if (
                    len(parts) >= 2
                    and parts[1].isdigit()
                ):
                    amount = int(parts[1])

                    reply_to = msg.get(
                        "reply_to_message"
                    )

                    target = (
                        reply_to["from"]["id"]
                        if reply_to
                        else user_id
                    )

                    target_name = (
                        reply_to["from"].get(
                            "first_name",
                            "Игрок"
                        )
                        if reply_to
                        else "себе"
                    )

                    get_user(
                        target,
                        target_name
                    )

                    update_balance(
                        target,
                        amount
                    )

                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** "
                        f"Выдано **+{amount}$** "
                        f"({target_name})!"
                    )

                    return

            elif text_lower.startswith("/take"):
                reply_to = msg.get(
                    "reply_to_message"
                )

                if (
                    reply_to
                    and len(parts) >= 2
                    and parts[1].isdigit()
                ):
                    target = reply_to["from"]["id"]
                    amount = int(parts[1])

                    get_user(
                        target,
                        reply_to["from"].get(
                            "first_name",
                            "Игрок"
                        )
                    )

                    update_balance(
                        target,
                        -amount
                    )

                    async_send_message(
                        chat_id,
                        f"👑 **Админ-действие:** "
                        f"Изъято **-{amount}$** у "
                        f"{reply_to['from'].get('first_name', 'Игрок')}!"
                    )

                    return

        # =========================
        # PAY
        # =========================

        if text_lower.startswith("/pay"):
            reply_to = msg.get(
                "reply_to_message"
            )

            parts = text.split()

            if (
                not reply_to
                or len(parts) < 2
                or not parts[1].isdigit()
            ):
                async_send_message(
                    chat_id,
                    "ℹ️ **Как переводить:** "
                    "ответьте на сообщение игрока "
                    "командой `/pay <сумма>` "
                    "(например, `/pay 1000`)."
                )
                return

            target = reply_to["from"]["id"]

            if target == user_id:
                async_send_message(
                    chat_id,
                    "❌ Нельзя перевести самому себе!"
                )
                return

            amount = int(parts[1])

            if amount <= 0:
                async_send_message(
                    chat_id,
                    "❌ Сумма должна быть больше нуля!"
                )
                return

            get_user(
                target,
                reply_to["from"].get(
                    "first_name",
                    "Игрок"
                )
            )

            my_balance = get_user_balance(
                user_id
            )

            if my_balance < amount:
                async_send_message(
                    chat_id,
                    "❌ У вас недостаточно "
                    "наличных для перевода!"
                )
                return

            cursor.execute(
                """
                UPDATE users
                SET balance = balance - %s
                WHERE user_id = %s
                """,
                (
                    amount,
                    user_id
                )
            )

            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    amount,
                    target
                )
            )

            conn.commit()

            target_name = reply_to["from"].get(
                "first_name",
                "Игрок"
            )

            async_send_message(
                chat_id,
                f"✅ Вы успешно перевели "
                f"**{amount}$** игроку "
                f"**{target_name}**!"
            )

            return

        # =========================
        # DUEL
        # =========================

        if text_lower.startswith("/duel"):
            reply_to = msg.get(
                "reply_to_message"
            )

            parts = text.split()

            if (
                not reply_to
                or len(parts) < 2
                or not parts[1].isdigit()
            ):
                async_send_message(
                    chat_id,
                    "⚔️ **Как дуэлиться:** "
                    "ответьте на сообщение игрока "
                    "командой `/duel <ставка>` "
                    "(например, `/duel 500`). "
                    "Шанс победы 50/50."
                )
                return

            target = reply_to["from"]["id"]

            if target == user_id:
                async_send_message(
                    chat_id,
                    "❌ Нельзя вызвать на дуэль "
                    "самого себя!"
                )
                return

            stake = int(parts[1])

            if stake < 100:
                async_send_message(
                    chat_id,
                    "❌ Минимальная ставка "
                    "для дуэли — 100$!"
                )
                return

            get_user(
                target,
                reply_to["from"].get(
                    "first_name",
                    "Игрок"
                )
            )

            my_balance = get_user_balance(
                user_id
            )

            target_balance = get_user_balance(
                target
            )

            if (
                my_balance < stake
                or target_balance < stake
            ):
                async_send_message(
                    chat_id,
                    "❌ У одного из участников "
                    "недостаточно средств "
                    "для такой ставки!"
                )
                return

            target_name = reply_to["from"].get(
                "first_name",
                "Игрок"
            )

            if random.random() < 0.5:
                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id = %s
                    """,
                    (
                        stake,
                        user_id
                    )
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s
                    WHERE user_id = %s
                    """,
                    (
                        stake,
                        target
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"⚔️ **Дуэль завершена!** "
                    f"Вы победили **{target_name}** "
                    f"и забрали **+{stake}$**!"
                )

            else:
                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s
                    WHERE user_id = %s
                    """,
                    (
                        stake,
                        user_id
                    )
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id = %s
                    """,
                    (
                        stake,
                        target
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"⚔️ **Дуэль завершена!** "
                    f"Соперник **{target_name}** "
                    f"оказался сильнее, "
                    f"вы проиграли **-{stake}$**."
                )

            return

        # =========================
        # ROB
        # =========================

        if text_lower.startswith("/rob"):
            reply_to = msg.get(
                "reply_to_message"
            )

            if not reply_to:
                async_send_message(
                    chat_id,
                    "🕶 **Как грабить:** "
                    "ответьте на сообщение игрока "
                    "командой `/rob` "
                    "(кулдаун 15 мин, шанс 40%)."
                )
                return

            target = reply_to["from"]["id"]

            if target == user_id:
                async_send_message(
                    chat_id,
                    "❌ Нельзя ограбить самого себя!"
                )
                return

            current_time = int(time.time())

            cursor.execute(
                """
                SELECT last_rob
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()
            last_rob = row[0] if row else 0

            if current_time - last_rob < 900:
                remaining = (
                    900 -
                    (current_time - last_rob)
                )

                async_send_message(
                    chat_id,
                    f"⏳ Кулдаун на ограбления: "
                    f"еще {int(remaining // 60)} мин."
                )

                return

            get_user(
                target,
                reply_to["from"].get(
                    "first_name",
                    "Игрок"
                )
            )

            target_balance = get_user_balance(
                target
            )

            cursor.execute(
                """
                UPDATE users
                SET last_rob = %s
                WHERE user_id = %s
                """,
                (
                    current_time,
                    user_id
                )
            )

            conn.commit()

            target_name = reply_to["from"].get(
                "first_name",
                "Игрок"
            )

            if target_balance < 100:
                async_send_message(
                    chat_id,
                    f"🕶 У **{target_name}** "
                    "слишком мало наличных "
                    "в кармане, грабить бессмысленно."
                )
                return

            if random.random() < 0.40:
                loot = min(
                    target_balance,
                    random.randint(150, 1500)
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id = %s
                    """,
                    (
                        loot,
                        user_id
                    )
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s
                    WHERE user_id = %s
                    """,
                    (
                        loot,
                        target
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"🕶 **Успешный грабеж!** "
                    f"Вы украли **{loot}$** "
                    f"у **{target_name}**!"
                )

            else:
                fine = random.randint(
                    100,
                    500
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET balance = GREATEST(0, balance - %s)
                    WHERE user_id = %s
                    """,
                    (
                        fine,
                        user_id
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"🚨 **Полиция пресекла попытку!** "
                    f"Вас поймали при ограблении "
                    f"**{target_name}**, "
                    f"штраф **-{fine}$**."
                )

            return

        # =========================
        # BANK INPUT
        # =========================

        if (
            user_id in user_states
            and not text.startswith("/")
        ):
            state = user_states[user_id]
            action = state.get("action")

            cursor.execute(
                """
                SELECT balance, bank_balance
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if not row:
                return

            my_balance, bank_balance = row

            if action == "bank_deposit_amount":
                amount = parse_amount(
                    text,
                    my_balance
                )

                del user_states[user_id]

                if (
                    amount <= 0
                    or my_balance < amount
                ):
                    async_send_message(
                        chat_id,
                        "❌ Недостаточно средств "
                        "или неверная сумма!"
                    )
                    return

                current_time = int(
                    time.time()
                )

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        balance = balance - %s,
                        bank_balance = bank_balance + %s,
                        deposit_created = %s,
                        deposit_rate = 0.05,
                        last_auto_interest = %s
                    WHERE user_id = %s
                    """,
                    (
                        amount,
                        amount,
                        current_time,
                        current_time,
                        user_id
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"🏦 **Депозит пополнен!**\n"
                    f"💵 Внесено: **{amount}$**"
                )

                return

            if action == "bank_withdraw_amount":
                amount = parse_amount(
                    text,
                    bank_balance
                )

                del user_states[user_id]

                if (
                    amount <= 0
                    or bank_balance < amount
                ):
                    async_send_message(
                        chat_id,
                        "❌ Недостаточно средств!"
                    )
                    return

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        balance = balance + %s,
                        bank_balance = bank_balance - %s
                    WHERE user_id = %s
                    """,
                    (
                        amount,
                        amount,
                        user_id
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    f"🏦 Вы успешно сняли "
                    f"с депозита **{amount}$**!"
                )

                return

        # =========================
        # MAIN MENU
        # =========================

        if (
            text.startswith("/start")
            or text == "📱 Главное меню"
        ):
            async_send_message(
                chat_id,
                f"🏰 **RP Мир | Главное меню**\n"
                f"Приветствуем, {first_name}!",
                reply_markup=main_bottom_keyboard
            )

            async_send_message(
                chat_id,
                "👇 Выберите раздел:",
                reply_markup=main_inline_menu
            )

        # =========================
        # PROFILE
        # =========================

        elif text in [
            "👤 Мой профиль",
            "/profile"
        ]:
            cursor.execute(
                """
                SELECT
                    balance,
                    job,
                    spouse_id,
                    house,
                    car,
                    bank_balance,
                    business,
                    exp
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if not row:
                return

            (
                balance,
                job,
                spouse_id,
                house,
                car,
                bank_balance,
                business,
                exp
            ) = row

            spouse_text = (
                f"💍 В браке с: "
                f"{get_user_name(spouse_id)}"
                if spouse_id
                else "💍 Статус: Холост"
            )

            admin_badge = (
                "👑 **Статус:** Владелец / "
                "Администратор "
                "(@Stariy_bog1336)\n"
                if is_admin(
                    user_id,
                    username
                )
                else ""
            )

            async_send_message(
                chat_id,
                f"👤 **Ваш RP Профиль:**\n"
                f"{admin_badge}"
                f"🆔 ID: `{user_id}`\n"
                f"📝 Имя: {first_name}\n"
                f"🔥 Опыт развитости: **{exp} EXP**\n"
                f"💰 Наличные: **{balance}$**\n"
                f"🏦 В банке: **{bank_balance}$**\n"
                f"💼 Работа: **{job}**\n"
                f"🏢 Бизнес: **{business}**\n"
                f"🏠 Дом: **{house}**\n"
                f"🚗 Авто: **{car}**\n"
                f"{spouse_text}"
            )

        # =========================
        # HELP
        # =========================

        elif text in [
            "ℹ️ Помощь",
            "/help"
        ]:
            async_send_message(
                chat_id,
                "📖 **Справочное бюро**\n\n"
                "Выберите нужную категорию "
                "из меню ниже:",
                reply_markup=help_inline_menu
            )

        # =========================
        # DAILY BONUS
        # =========================

        elif text == "🎁 Ежедневный бонус":
            current_time = int(time.time())

            cursor.execute(
                """
                SELECT last_bonus
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            last_bonus = (
                row[0]
                if row
                else 0
            )

            if current_time - last_bonus >= 86400:
                cursor.execute(
                    """
                    UPDATE users
                    SET
                        balance = balance + 500,
                        exp = exp + 5,
                        last_bonus = %s
                    WHERE user_id = %s
                    """,
                    (
                        current_time,
                        user_id
                    )
                )

                conn.commit()

                async_send_message(
                    chat_id,
                    "🎉 Вы получили "
                    "ежедневный бонус "
                    "**+500$** и **+5 EXP**!"
                )

            else:
                remaining = (
                    86400 -
                    (current_time - last_bonus)
                )

                async_send_message(
                    chat_id,
                    f"⏳ Бонус доступен через: "
                    f"{int(remaining // 3600)} ч. "
                    f"{int((remaining % 3600) // 60)} мин."
                )

        return

    # =========================
    # CALLBACK QUERY
    # =========================

    if "callback_query" not in update:
        return

    call = update["callback_query"]

    message = call.get("message")

    if not message:
        return

    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    data = call.get("data")

    # =========================
    # MAIN MENU
    # =========================

    if data == "menu_main":
        async_edit_message_text(
            chat_id,
            message_id,
            "👇 **Главное интерактивное меню:**",
            reply_markup=main_inline_menu
        )

    # =========================
    # HELP
    # =========================

    elif data == "menu_help":
        async_edit_message_text(
            chat_id,
            message_id,
            "📖 **Справочное бюро**\n\n"
            "Выберите нужную категорию "
            "из меню ниже:",
            reply_markup=help_inline_menu
        )

    # =========================
    # CASINO MENU
    # =========================

    elif data == "menu_casino":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "🎰 **VIP Казино**\n\n"
                "Выберите игру:\n"
                "• 🔴/⚫ Красное/Черное — "
                "шанс 50/50, куш x2 "
                "(ставка 500$)\n"
                "• 🎰 Слот-машина — "
                "анимационный стикер ТГ "
                "(ставка 500$)\n"
                "• 🎲 Кости — "
                "анимационный кубик "
                "против дилера "
                "(ставка 1000$)\n"
                "• 🃏 Блэкджек (21) — "
                "карточная игра против "
                "банка (ставка 1000$)"
            ),
            reply_markup=casino_menu_keyboard
        )

    # =========================
    # ROULETTE
    # =========================

    elif data in [
        "cas_roul_red",
        "cas_roul_black"
    ]:
        my_balance = get_user_balance(
            user_id
        )

        bet = 500

        if my_balance < bet:
            async_answer_callback(
                call["id"],
                f"❌ Нужно минимум {bet}$ "
                "на балансе!"
            )
            return

        win = random.choice([
            True,
            False
        ])

        color_text = (
            "🔴 Красное"
            if data == "cas_roul_red"
            else "⚫ Черное"
        )

        if win:
            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    bet,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎉 Выпал правильный сектор! "
                f"Вы выиграли +{bet}$!"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🎰 **Рулетка ({color_text})**\n"
                f"🎉 **Победа!** "
                f"Вы забрали **+{bet}$**!",
                reply_markup=back_to_main_kb
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET balance = balance - %s
                WHERE user_id = %s
                """,
                (
                    bet,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"😢 Промах, -{bet}$"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🎰 **Рулетка ({color_text})**\n"
                f"😢 **Проигрыш** —{bet}$. "
                "Фортуна отвернулась.",
                reply_markup=back_to_main_kb
            )

    # =========================
    # SLOTS
    # =========================

    elif data == "cas_slots_500":
        my_balance = get_user_balance(
            user_id
        )

        bet = 500

        if my_balance < bet:
            async_answer_callback(
                call["id"],
                f"❌ Нужно минимум {bet}$ "
                "на балансе!"
            )
            return

        cursor.execute(
            """
            UPDATE users
            SET balance = balance - %s
            WHERE user_id = %s
            """,
            (
                bet,
                user_id
            )
        )

        conn.commit()

        async_send_dice(
            chat_id,
            "🎰"
        )

        slot_win = random.random() < 0.35

        if slot_win:
            payout = bet * 3

            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    payout,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎰 ДЖЕКПОТ! "
                f"Выиграно +{payout}$!"
            )

        else:
            async_answer_callback(
                call["id"],
                f"🎰 Комбинация мимо, -{bet}$"
            )

    # =========================
    # DICE
    # =========================

    elif data == "cas_dice_1000":
        my_balance = get_user_balance(
            user_id
        )

        bet = 1000

        if my_balance < bet:
            async_answer_callback(
                call["id"],
                f"❌ Нужно минимум {bet}$ "
                "на балансе!"
            )
            return

        cursor.execute(
            """
            UPDATE users
            SET balance = balance - %s
            WHERE user_id = %s
            """,
            (
                bet,
                user_id
            )
        )

        conn.commit()

        async_send_dice(
            chat_id,
            "🎲"
        )

        my_dice = random.randint(1, 6)
        bot_dice = random.randint(1, 6)

        if my_dice > bot_dice:
            win_amount = bet * 2

            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    win_amount,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎲 У вас {my_dice}, "
                f"у бота {bot_dice}. "
                f"Выиграли +{win_amount}$!"
            )

        elif my_dice < bot_dice:
            async_answer_callback(
                call["id"],
                f"🎲 У вас {my_dice}, "
                f"у бота {bot_dice}. "
                f"Проигрыш -{bet}$!"
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    bet,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎲 Ничья ({my_dice}:{bot_dice}), "
                "ставка возвращена."
            )

    # =========================
    # BLACKJACK START
    # =========================

    elif data == "cas_bj_start":
        my_balance = get_user_balance(
            user_id
        )

        bet = 1000

        if my_balance < bet:
            async_answer_callback(
                call["id"],
                f"❌ Нужно минимум {bet}$ "
                "для игры в 21!"
            )
            return

        cursor.execute(
            """
            UPDATE users
            SET balance = balance - %s
            WHERE user_id = %s
            """,
            (
                bet,
                user_id
            )
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
            "A"
        ] * 4

        random.shuffle(deck)

        player_hand = [
            deck.pop(),
            deck.pop()
        ]

        dealer_hand = [
            deck.pop(),
            deck.pop()
        ]

        blackjack_games[user_id] = {
            "deck": deck,
            "player": player_hand,
            "dealer": dealer_hand,
            "bet": bet
        }

        player_score = calc_score(
            player_hand
        )

        async_edit_message_text(
            chat_id,
            message_id,
            f"🃏 **Блэкджек (21)**\n"
            f"Ваши карты: "
            f"`{' '.join(player_hand)}` "
            f"(Счет: **{player_score}**)\n"
            f"Карта дилера: "
            f"`{dealer_hand[0]}` [скрыта]\n\n"
            "Ваш ход:",
            reply_markup=bj_game_keyboard
        )

    # =========================
    # BLACKJACK HIT
    # =========================

    elif data == "cas_bj_hit":
        game = blackjack_games.get(
            user_id
        )

        if not game:
            async_answer_callback(
                call["id"],
                "❌ Активная игра не найдена!"
            )
            return

        game["player"].append(
            game["deck"].pop()
        )

        player_score = calc_score(
            game["player"]
        )

        if player_score > 21:
            del blackjack_games[user_id]

            async_edit_message_text(
                chat_id,
                message_id,
                f"🃏 **Блэкджек (21)**\n"
                f"Ваши карты: "
                f"`{' '.join(game['player'])}` "
                f"(Счет: **перебор {player_score}**)\n\n"
                f"😢 **Вы перебрали и "
                f"проиграли ставку "
                f"(-{game['bet']}$)!**",
                reply_markup=back_to_main_kb
            )

        else:
            async_edit_message_text(
                chat_id,
                message_id,
                f"🃏 **Блэкджек (21)**\n"
                f"Ваши карты: "
                f"`{' '.join(game['player'])}` "
                f"(Счет: **{player_score}**)\n"
                f"Карта дилера: "
                f"`{game['dealer'][0]}` [скрыта]\n\n"
                "Ваш ход:",
                reply_markup=bj_game_keyboard
            )

    # =========================
    # BLACKJACK STAND
    # =========================

    elif data == "cas_bj_stand":
        game = blackjack_games.pop(
            user_id,
            None
        )

        if not game:
            async_answer_callback(
                call["id"],
                "❌ Активная игра не найдена!"
            )
            return

        player_score = calc_score(
            game["player"]
        )

        dealer_score = calc_score(
            game["dealer"]
        )

        while dealer_score < 17:
            game["dealer"].append(
                game["deck"].pop()
            )

            dealer_score = calc_score(
                game["dealer"]
            )

        result_text = (
            "🃏 **Итоги Блэкджека**\n"
            f"Ваши карты: "
            f"`{' '.join(game['player'])}` "
            f"(Счет: **{player_score}**)\n"
            f"Карты дилера: "
            f"`{' '.join(game['dealer'])}` "
            f"(Счет: **{dealer_score}**)\n\n"
        )

        bet = game["bet"]

        if (
            dealer_score > 21
            or player_score > dealer_score
        ):
            win_amount = bet * 2

            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    win_amount,
                    user_id
                )
            )

            conn.commit()

            result_text += (
                f"🎉 **Победа! "
                f"Вы выиграли +{win_amount}$!**"
            )

        elif player_score < dealer_score:
            result_text += (
                f"😢 **Дилер выиграл, "
                f"вы проиграли -{bet}$!**"
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                """,
                (
                    bet,
                    user_id
                )
            )

            conn.commit()

            result_text += (
                f"🤝 **Ничья! "
                f"Ставка возвращена (+{bet}$)**"
            )

        async_edit_message_text(
            chat_id,
            message_id,
            result_text,
            reply_markup=back_to_main_kb
        )

    # =========================
    # JOBS
    # =========================

    elif data == "menu_jobs":
        cursor.execute(
            """
            SELECT job, last_work, exp
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        job, last_work, exp = row

        job_buttons = []

        for job_name, job_info in JOBS.items():
            job_buttons.append(
                [
                    {
                        "text": (
                            f"{'✅ ' if job == job_name else ''}"
                            f"{job_name} — "
                            f"{job_info['salary']}$ "
                            f"(требуется "
                            f"{job_info['min_exp']} EXP)"
                        ),
                        "callback_data": (
                            f"set_job_{job_name}"
                        )
                    }
                ]
            )

        job_buttons.append(
            [
                {
                    "text": (
                        "⚒ Отработать смену "
                        "(+Доход & EXP)"
                    ),
                    "callback_data": "do_work"
                }
            ]
        )

        job_buttons.append(
            [
                {
                    "text": "⬅️ Назад",
                    "callback_data": "menu_main"
                }
            ]
        )

        async_edit_message_text(
            chat_id,
            message_id,
            f"💼 **Центр Трудоустройства**\n\n"
            f"Ваш текущий опыт: **{exp} EXP**\n"
            f"Ваша профессия: **{job}**\n\n"
            "Чем выше ваш опыт и должность, "
            "тем больше вы зарабатываете!",
            reply_markup={
                "inline_keyboard": job_buttons
            }
        )

    # =========================
    # SET JOB
    # =========================

    elif data.startswith("set_job_"):
        job_name = data.replace(
            "set_job_",
            "",
            1
        )

        if job_name not in JOBS:
            return

        cursor.execute(
            """
            SELECT exp
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        user_exp = row[0]

        if user_exp < JOBS[job_name]["min_exp"]:
            async_answer_callback(
                call["id"],
                f"❌ Не хватает опыта! "
                f"Требуется "
                f"{JOBS[job_name]['min_exp']} EXP."
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET job = %s
                WHERE user_id = %s
                """,
                (
                    job_name,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎉 Вы устроились: "
                f"{job_name}!"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🎉 Вы успешно устроились "
                f"на работу: **{job_name}**!",
                reply_markup=back_to_main_kb
            )

    # =========================
    # WORK
    # =========================

    elif data == "do_work":
        current_time = int(
            time.time()
        )

        cursor.execute(
            """
            SELECT job, last_work, exp
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        job, last_work, exp = row

        if job == "Безработный":
            async_answer_callback(
                call["id"],
                "❌ Выберите профессию "
                "в списке!"
            )

        elif current_time - last_work >= 600:
            salary = (
                JOBS[job]["salary"]
                + exp * 2
            )

            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance + %s,
                    exp = exp + 10,
                    last_work = %s
                WHERE user_id = %s
                """,
                (
                    salary,
                    current_time,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"💰 Заработано: "
                f"+{salary}$ и +10 EXP!"
            )

        else:
            remaining = (
                600 -
                (current_time - last_work)
            )

            async_answer_callback(
                call["id"],
                f"⏳ Отдых еще: "
                f"{int(remaining // 60)} мин. "
                f"{remaining % 60} сек."
            )

    # =========================
    # PROPERTY
    # =========================

    elif data == "menu_property":
        cursor.execute(
            """
            SELECT house, car
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        house, car = row

        property_buttons = [
            [
                {
                    "text": "🚗 Купить Автомобиль",
                    "callback_data": "buy_car_menu"
                }
            ],
            [
                {
                    "text": "🏠 Купить Недвижимость",
                    "callback_data": "buy_house_menu"
                }
            ],
            [
                {
                    "text": "⬅️ Назад",
                    "callback_data": "menu_main"
                }
            ]
        ]

        async_edit_message_text(
            chat_id,
            message_id,
            f"🏰 **Рынок Имущества**\n\n"
            f"🏠 Ваш дом: **{house}**\n"
            f"🚗 Ваше авто: **{car}**\n\n"
            "Выберите категорию для покупки:",
            reply_markup={
                "inline_keyboard": property_buttons
            }
        )

    # =========================
    # CAR MENU
    # =========================

    elif data == "buy_car_menu":
        car_buttons = []

        for car_name, car_price in CARS.items():
            car_buttons.append(
                [
                    {
                        "text": (
                            f"{car_name} — "
                            f"{car_price}$"
                        ),
                        "callback_data": (
                            f"buycar_{car_name}"
                        )
                    }
                ]
            )

        car_buttons.append(
            [
                {
                    "text": "⬅️ Назад",
                    "callback_data": "menu_property"
                }
            ]
        )

        async_edit_message_text(
            chat_id,
            message_id,
            "🚗 **Автосалон**\n"
            "Выберите машину для покупки:",
            reply_markup={
                "inline_keyboard": car_buttons
            }
        )

    # =========================
    # BUY CAR
    # =========================

    elif data.startswith("buycar_"):
        car_name = data.replace(
            "buycar_",
            "",
            1
        )

        if car_name not in CARS:
            return

        price = CARS[car_name]
        balance = get_user_balance(
            user_id
        )

        if balance < price:
            async_answer_callback(
                call["id"],
                f"❌ Не хватает "
                f"{price - balance}$!"
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance - %s,
                    car = %s
                WHERE user_id = %s
                """,
                (
                    price,
                    car_name,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🏎 Куплено: {car_name}!"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏎 Поздравляем с "
                f"покупкой авто "
                f"**{car_name}**!",
                reply_markup=back_to_main_kb
            )

    # =========================
    # HOUSE MENU
    # =========================

    elif data == "buy_house_menu":
        house_buttons = []

        for house_name, house_price in HOUSES.items():
            house_buttons.append(
                [
                    {
                        "text": (
                            f"{house_name} — "
                            f"{house_price}$"
                        ),
                        "callback_data": (
                            f"buyhouse_{house_name}"
                        )
                    }
                ]
            )

        house_buttons.append(
            [
                {
                    "text": "⬅️ Назад",
                    "callback_data": "menu_property"
                }
            ]
        )

        async_edit_message_text(
            chat_id,
            message_id,
            "🏠 **Агентство "
            "Недвижимости**\n"
            "Выберите жилье для покупки:",
            reply_markup={
                "inline_keyboard": house_buttons
            }
        )

    # =========================
    # BUY HOUSE
    # =========================

    elif data.startswith("buyhouse_"):
        house_name = data.replace(
            "buyhouse_",
            "",
            1
        )

        if house_name not in HOUSES:
            return

        price = HOUSES[house_name]
        balance = get_user_balance(
            user_id
        )

        if balance < price:
            async_answer_callback(
                call["id"],
                f"❌ Не хватает "
                f"{price - balance}$!"
            )

        else:
            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance - %s,
                    house = %s
                WHERE user_id = %s
                """,
                (
                    price,
                    house_name,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🏠 Куплено: {house_name}!"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏠 Поздравляем с "
                f"покупкой жилья "
                f"**{house_name}**!",
                reply_markup=back_to_main_kb
            )

    # =========================
    # BANK
    # =========================

    elif data == "menu_bank":
        cursor.execute(
            """
            SELECT
                bank_balance,
                deposit_rate,
                balance
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        bank_balance, deposit_rate, my_balance = row

        bank_keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "📥 Внести на депозит",
                        "callback_data": "bank_dep_prompt"
                    },
                    {
                        "text": "📤 Снять со счета",
                        "callback_data": "bank_wd_prompt"
                    }
                ],
                [
                    {
                        "text": "⬅️ Назад",
                        "callback_data": "menu_main"
                    }
                ]
            ]
        }

        async_edit_message_text(
            chat_id,
            message_id,
            f"🏦 **Центральный Банк**\n\n"
            f"💵 Наличные: **{my_balance}$**\n"
            f"🏦 На депозите: **{bank_balance}$**\n"
            f"📈 Начисление: "
            f"**{deposit_rate * 100:.0f}% в час** "
            "(автоматически)",
            reply_markup=bank_keyboard
        )

    # =========================
    # BANK DEPOSIT
    # =========================

    elif data == "bank_dep_prompt":
        user_states[user_id] = {
            "action": "bank_deposit_amount"
        }

        async_send_message(
            chat_id,
            "📥 **Пополнение депозита**\n"
            "Введите сумму, которую хотите "
            "положить в банк "
            "(или напишите `все`):"
        )

    # =========================
    # BANK WITHDRAW
    # =========================

    elif data == "bank_wd_prompt":
        user_states[user_id] = {
            "action": "bank_withdraw_amount"
        }

        async_send_message(
            chat_id,
            "📤 **Снятие с депозита**\n"
            "Введите сумму, которую хотите "
            "снять из банка "
            "(или напишите `все`):"
        )

    # =========================
    # BUSINESS
    # =========================

    elif data == "menu_business":
        cursor.execute(
            """
            SELECT
                business,
                last_biz_collect
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        business = (
            row[0]
            if row
            else "Отсутствует"
        )

        business_buttons = []

        if business == "Отсутствует":
            for business_name, business_info in BUSINESSES.items():
                business_buttons.append(
                    [
                        {
                            "text": (
                                f"Купить "
                                f"{business_name} — "
                                f"{business_info['price']}$ "
                                f"(+"
                                f"{business_info['income']}"
                                f"$/2ч)"
                            ),
                            "callback_data": (
                                f"buy_biz_{business_name}"
                            )
                        }
                    ]
                )

        else:
            business_buttons.append(
                [
                    {
                        "text": (
                            f"💵 Собрать прибыль "
                            f"({business})"
                        ),
                        "callback_data": "collect_biz"
                    }
                ]
            )

        business_buttons.append(
            [
                {
                    "text": "⬅️ Назад",
                    "callback_data": "menu_main"
                }
            ]
        )

        async_edit_message_text(
            chat_id,
            message_id,
            f"🏢 **Управление Бизнесом**\n\n"
            f"Ваш текущий бизнес: "
            f"**{business}**",
            reply_markup={
                "inline_keyboard": business_buttons
            }
        )

    # =========================
    # BUY BUSINESS
    # =========================

    elif data.startswith("buy_biz_"):
        business_name = data.replace(
            "buy_biz_",
            "",
            1
        )

        if business_name not in BUSINESSES:
            return

        price = BUSINESSES[
            business_name
        ]["price"]

        balance = get_user_balance(
            user_id
        )

        if balance < price:
            async_answer_callback(
                call["id"],
                f"❌ Не хватает "
                f"{price - balance}$!"
            )

        else:
            current_time = int(
                time.time()
            )

            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance - %s,
                    business = %s,
                    last_biz_collect = %s
                WHERE user_id = %s
                """,
                (
                    price,
                    business_name,
                    current_time,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"🎉 Куплено: "
                f"{business_name}!"
            )

            async_edit_message_text(
                chat_id,
                message_id,
                f"🎉 Вы успешно купили "
                f"**{business_name}**!",
                reply_markup=back_to_main_kb
            )

    # =========================
    # COLLECT BUSINESS
    # =========================

    elif data == "collect_biz":
        current_time = int(
            time.time()
        )

        cursor.execute(
            """
            SELECT
                business,
                last_biz_collect,
                exp
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        if not row:
            return

        business, last_collect, exp = row

        if business == "Отсутствует":
            async_answer_callback(
                call["id"],
                "❌ У вас нет бизнеса!"
            )
            return

        if current_time - last_collect >= 7200:
            income = (
                BUSINESSES[business]["income"]
                + exp * 10
            )

            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance + %s,
                    last_biz_collect = %s
                WHERE user_id = %s
                """,
                (
                    income,
                    current_time,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                f"💵 Собрано: +{income}$!"
            )

        else:
            remaining = (
                7200 -
                (current_time - last_collect)
            )

            async_answer_callback(
                call["id"],
                f"⏳ До сбора кассы: "
                f"{int(remaining // 3600)} ч. "
                f"{int((remaining % 3600) // 60)} мин."
            )

    # =========================
    # HELP: DEVELOPMENT
    # =========================

    elif data == "help_dev":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "🛠 **О разработке и ИИ**\n\n"
                "• Бот создан на Python + "
                "PostgreSQL (Neon).\n"
                "• Архитектура: потоковый "
                "асинхронный polling + "
                "HTTP-health check для Render.\n"
                "• Администратор и владелец: "
                "**@Stariy_bog1336**"
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # HELP: JOBS
    # =========================

    elif data == "help_jobs":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "💼 **Работа и Заработок**\n\n"
                "• Устраивайтесь на работу "
                "через меню "
                "(`💼 Работа и Развитие`).\n"
                "• Опыт (EXP) растет за "
                "каждую смену (+10 EXP) и "
                "за ежедневный бонус "
                "(+5 EXP).\n"
                "• Больше опыта = выше "
                "зарплата и бонус к доходу "
                "с бизнеса."
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # HELP: BANK
    # =========================

    elif data == "help_bank":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "🏦 **Банк и Депозиты**\n\n"
                "• Пополняйте счет наличными.\n"
                "• На депозит автоматически "
                "начисляется **5% в час** "
                "при обращении к боту."
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # HELP: PROPERTY
    # =========================

    elif data == "help_property":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "🏰 **Имущество и Бизнес**\n\n"
                "• Покупайте машины "
                "(6 уровней) и дома "
                "(6 уровней) для статуса "
                "в профиле.\n"
                "• Покупайте бизнесы "
                "(Автомойка, Пиццерия, "
                "Ферма, Отель, БЦ, "
                "IT-Корпорация) для "
                "пассивного дохода "
                "раз в 2 часа."
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # HELP: RP
    # =========================

    elif data == "help_rp":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "⚔️ **Дуэли, Ограбления "
                "и Переводы**\n\n"
                "• **Перевод:** ответьте "
                "`/pay <сумма>` на сообщение "
                "игрока.\n"
                "• **Дуэль:** ответьте "
                "`/duel <ставка>` на сообщение "
                "игрока (шанс 50/50).\n"
                "• **Ограбление:** ответьте "
                "`/rob` на сообщение игрока "
                "(кулдаун 15 мин, шанс 40%)."
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # HELP: CASINO
    # =========================

    elif data == "help_casino":
        async_edit_message_text(
            chat_id,
            message_id,
            (
                "🎰 **Казино и Игры**\n\n"
                "• Играйте в "
                "Красное/Черное, "
                "анимационные слоты "
                "(`🎰`), кости против "
                "бота (`🎲`) или "
                "карточный блэкджек (21)."
            ),
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "⬅️ Назад",
                            "callback_data": "menu_help"
                        }
                    ]
                ]
            }
        )

    # =========================
    # ADVERTISEMENT
    # =========================

    elif data == "menu_ad":
        cursor.execute(
            """
            SELECT last_ad
            FROM users
            WHERE user_id = %s
            """,
            (user_id,)
        )

        row = cursor.fetchone()

        last_ad = (
            row[0]
            if row
            else 0
        )

        current_time = int(
            time.time()
        )

        if current_time - last_ad >= 1800:
            cursor.execute(
                """
                UPDATE users
                SET
                    balance = balance + 300,
                    last_ad = %s
                WHERE user_id = %s
                """,
                (
                    current_time,
                    user_id
                )
            )

            conn.commit()

            async_answer_callback(
                call["id"],
                "📺 Начислено +300$ "
                "за просмотр рекламы!"
            )

        else:
            remaining = (
                1800 -
                (current_time - last_ad)
            )

            async_answer_callback(
                call["id"],
                f"⏳ Доступно через: "
                f"{int(remaining // 60)} мин."
            )

    # =========================
    # TOP 10
    # =========================

    elif data == "menu_top":
        cursor.execute(
            """
            SELECT
                first_name,
                (balance + bank_balance) AS total
            FROM users
            ORDER BY total DESC
            LIMIT 10
            """
        )

        top_users = cursor.fetchall()

        medals = [
            "🥇",
            "🥈",
            "🥉",
            "4️⃣",
            "5️⃣",
            "6️⃣",
            "7️⃣",
            "8️⃣",
            "9️⃣",
            "🔟"
        ]

        top_text = (
            "🏆 **ТОП-10 САМЫХ "
            "БОГАТЫХ ИГРОКОВ** 🏆\n\n"
        )

        for index, (name, total) in enumerate(
            top_users
        ):
            if index < len(medals):
                top_text += (
                    f"{medals[index]} "
                    f"{name} — {total}$\n"
                )

        async_edit_message_text(
            chat_id,
            message_id,
            top_text,
            reply_markup=back_to_main_kb
        )


# =========================
# MAIN
# =========================

def main():
    api_request(
        "deleteWebhook",
        {
            "drop_pending_updates": True
        }
    )

    print(
        "🚀 Бот запущен с полным "
        "интерактивным казино "
        "и PostgreSQL (Neon)!"
    )

    offset = 0

    while True:
        try:
            response = api_request(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 1
                }
            )

            if (
                response
                and response.get("ok")
            ):
                for update in response.get(
                    "result",
                    []
                ):
                    offset = (
                        update["update_id"] + 1
                    )

                    threading.Thread(
                        target=handle_update,
                        args=(update,),
                        daemon=True
                    ).start()

        except Exception as error:
            print(
                f"Ошибка polling: {error}"
            )

        time.sleep(0.1)


# =========================
# START
# =========================

if __name__ == "__main__":
    main()