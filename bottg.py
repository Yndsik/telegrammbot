import json
import random
import sqlite3
import ssl
import threading
import time
import urllib.parse
import urllib.request
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


# Фейковый сервер для прохождения проверки портов Render
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

TOKEN = "8932170200:AAHpxbAuLChcEkQqaIofxOBUfyN8eVyEvAM"
API_URL = f"https://api.telegram.org/bot{TOKEN}/"

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

user_cooldowns = {}
COOLDOWN_TIME = 0.2
user_states = {}

# --- 1. БАЗА ДАННЫХ И МИГРАЦИИ ---
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
    last_auto_interest INTEGER DEFAULT 0
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
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def get_user(user_id, first_name="Игрок"):
    cursor.execute(
        "SELECT user_id, first_name, balance, job, spouse_id, house, car, bank_balance, deposit_created, deposit_term_days, deposit_rate, last_auto_interest FROM users WHERE user_id = ?",
        (user_id,),
    )
    user = cursor.fetchone()
    if not user:
        cursor.execute(
            "INSERT INTO users (user_id, first_name, balance) VALUES (?, ?, 1000)",
            (user_id, first_name),
        )
        conn.commit()
        return (user_id, first_name, 1000, "Безработный", 0, "Отсутствует", "Отсутствует", 0, 0, 0, 0.05, 0)
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


# Начисление 5% каждый час (3600 сек)
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
        last_check = last_interest if last_interest > 0 else (dep_created if dep_created > 0 else curr_time)
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

pending_duels = {}
games_21 = {}


# --- 2. МНОГОПОТОЧНАЯ СЕТЕВАЯ ОТПРАВКА ---
def api_request(method: str, params: dict = None):
    url = API_URL + method
    try:
        data = json.dumps(params).encode('utf-8') if params else None
        headers = {'Content-Type': 'application/json'}
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, context=ssl_context, timeout=3) as response:
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


def async_edit_message_text(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    def _worker():
        params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        else:
            params["reply_markup"] = {"inline_keyboard": []}
        api_request("editMessageText", params)
    threading.Thread(target=_worker, daemon=True).start()


def async_answer_callback(callback_id: str, text: str):
    def _worker():
        api_request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": True})
    threading.Thread(target=_worker, daemon=True).start()


# --- 3. КЛАВИАТУРЫ ---
main_keyboard = {
    "keyboard": [
        [{"text": "🎰 Казино"}, {"text": "💼 Работа"}],
        [{"text": "🏦 Банк"}, {"text": "🏰 Имущество"}],
        [{"text": "👤 Профиль"}, {"text": "🏆 Топ богачей"}],
        [{"text": "🎁 Ежедневный бонус"}, {"text": "📺 Реклама (+300$)"}],
        [{"text": "ℹ️ Помощь / Команды"}],
    ],
    "resize_keyboard": True,
}

help_keyboard = {
    "inline_keyboard": [
        [{"text": "🛠 О разработке и ИИ", "callback_data": "help_about"}],
        [{"text": "💼 Работа и Заработок", "callback_data": "help_jobs"}],
        [{"text": "🏦 Банк и Депозиты", "callback_data": "help_bank"}],
        [{"text": "🏰 Имущество и Бизнес", "callback_data": "help_property"}],
        [{"text": "⚔️ Дуэли, Ограбления и Переводы", "callback_data": "help_rp"}],
        [{"text": "🎰 Казино и Игры", "callback_data": "help_casino"}],
    ]
}

back_to_help_kb = {
    "inline_keyboard": [
        [{"text": "⬅️ Назад в меню помощи", "callback_data": "help_main"}]
    ]
}

casino_menu_keyboard = {
    "inline_keyboard": [
        [{"text": "🎰 Рулетка", "callback_data": "play_roulette_menu"}],
        [{"text": "🃏 Игра 21 (Блэкджек)", "callback_data": "play_21_prompt"}],
        [{"text": "🎲 Кости", "callback_data": "play_dice_prompt"}],
    ]
}

game21_keyboard = {
    "inline_keyboard": [
        [{"text": "➕ Взять карту", "callback_data": "21_hit"}],
        [{"text": "✋ Хватит", "callback_data": "21_stand"}],
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


# --- 4. ОБРАБОТКА ОБНОВЛЕНИЙ ---
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

        # --- ОБРАБОТКА ВВОДА СУММ ---
        if user_id in user_states and not text.startswith("/"):
            state = user_states[user_id]
            action = state["action"]

            cursor.execute("SELECT balance, bank_balance FROM users WHERE user_id = ?", (user_id,))
            my_balance, bank_balance = cursor.fetchone()

            if action == "bank_deposit_amount":
                amount = parse_amount(text, my_balance)
                del user_states[user_id]

                if amount <= 0:
                    async_send_message(chat_id, "❌ Некорректная сумма! Операция отменена.")
                    return
                if my_balance < amount:
                    async_send_message(chat_id, f"❌ У вас недостаточно наличных! Ваш баланс: {my_balance}$.")
                    return

                curr_time = int(time.time())
                cursor.execute(
                    "UPDATE users SET balance = balance - ?, bank_balance = bank_balance + ?, deposit_created = ?, deposit_rate = 0.05, last_auto_interest = ? WHERE user_id = ?",
                    (amount, amount, curr_time, curr_time, user_id),
                )
                conn.commit()

                async_send_message(
                    chat_id,
                    f"🏦 **Депозит успешно пополнен!**\n\n"
                    f"💵 Внесено: **{amount}$**\n"
                    f"📈 Процентная ставка: **5% в час** (начисляется автоматически)\n"
                    f"🏦 Всего в банке: **{bank_balance + amount}$**",
                )
                return

            elif action == "bank_withdraw_amount":
                amount = parse_amount(text, bank_balance)
                del user_states[user_id]

                if amount <= 0:
                    async_send_message(chat_id, "❌ Некорректная сумма! Операция отменена.")
                    return
                if bank_balance < amount:
                    async_send_message(chat_id, f"❌ На депозите нет такой суммы! В банке: {bank_balance}$.")
                    return

                new_bank_bal = bank_balance - amount
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, bank_balance = ? WHERE user_id = ?",
                    (amount, new_bank_bal, user_id),
                )
                conn.commit()

                async_send_message(
                    chat_id,
                    f"🏦 Вы сняли с депозита **{amount}$**!\n"
                    f"Средства зачислены на ваш баланс наличных.",
                )
                return

            elif action == "roulette_bet_amount":
                choice = state["choice"]
                bet = parse_amount(text, my_balance)
                del user_states[user_id]

                if bet < 50:
                    async_send_message(chat_id, "❌ Минимальная ставка: 50$!")
                    return
                if my_balance < bet:
                    async_send_message(chat_id, f"❌ У вас недостаточно средств! Баланс: {my_balance}$.")
                    return

                spin = random.choices(["red", "black", "zero"], weights=[48, 48, 4], k=1)[0]

                if choice == spin:
                    mult = 14 if spin == "zero" else 2
                    win_amount = bet * mult - bet
                    update_balance(user_id, win_amount)
                    res_msg = f"🎉 **ВЫИГРЫШ!** Выпало **{spin.upper()}**. Вы получили +{win_amount}$!"
                else:
                    update_balance(user_id, -bet)
                    res_msg = f"🔻 **ПРОИГРЫШ!** Выпало **{spin.upper()}**. Потеряно -{bet}$."

                async_send_message(chat_id, f"🎰 **Рулетка (Ставка: {bet}$):**\n{res_msg}")
                return

            elif action == "21_bet_amount":
                bet = parse_amount(text, my_balance)
                del user_states[user_id]

                if bet < 100:
                    async_send_message(chat_id, "❌ Минимальная ставка в 21: 100$!")
                    return
                if my_balance < bet:
                    async_send_message(chat_id, f"❌ У вас недостаточно денег! Баланс: {my_balance}$.")
                    return

                player_hand = [get_card(), get_card()]
                dealer_hand = [get_card()]
                games_21[user_id] = {"player": player_hand, "dealer": dealer_hand, "bet": bet}

                p_score = calculate_score(player_hand)
                async_send_message(
                    chat_id,
                    f"🃏 **Игра 21 (Ставка: {bet}$)**\n\nВаши карты: {player_hand} ({p_score} очков)\nКарта дилера: {dealer_hand}",
                    reply_markup=game21_keyboard,
                )
                return

            elif action == "dice_bet_amount":
                bet = parse_amount(text, my_balance)
                del user_states[user_id]

                if bet < 50:
                    async_send_message(chat_id, "❌ Минимальная ставка: 50$!")
                    return
                if my_balance < bet:
                    async_send_message(chat_id, f"❌ У вас недостаточно денег! Баланс: {my_balance}$.")
                    return

                user_dice = random.randint(1, 6) + random.randint(1, 6)
                bot_dice = random.randint(1, 6) + random.randint(1, 6)

                if user_dice > bot_dice:
                    update_balance(user_id, bet)
                    res_msg = f"🏆 **ВЫ ВЫИГРАЛИ!** Вы получили +{bet}$!"
                elif user_dice < bot_dice:
                    update_balance(user_id, -bet)
                    res_msg = f"💀 **ВЫ ПРОИГРАЛИ!** Потеряно -{bet}$."
                else:
                    res_msg = "🤝 **НИЧЬЯ!** Ставка возвращена."

                async_send_message(
                    chat_id,
                    f"🎲 **Бросок костей (Ставка: {bet}$)**\n\n"
                    f"🎯 Ваши очки: **{user_dice}**\n"
                    f"🤖 Очки бота: **{bot_dice}**\n\n"
                    f"{res_msg}",
                )
                return

        # --- ОБРАБОТКА RP-КОМАНД В ЧАТЕ (ЧЕРЕЗ REPLY) ---
        reply_to = msg.get("reply_to_message")

        if reply_to:
            target_id = reply_to["from"]["id"]
            target_name = reply_to["from"].get("first_name", "Игрок")

            # 1. Перевод денег (/pay 500 или дать 500)
            if text_lower.startswith(("/pay", "дать", "передать")):
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя переводить деньги самому себе!")
                else:
                    get_user(target_id, target_name)
                    parts = text.split()
                    if len(parts) >= 2:
                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                        my_bal = cursor.fetchone()[0]
                        amount = parse_amount(parts[1], my_bal)

                        if amount <= 0:
                            async_send_message(chat_id, "❌ Укажите корректную сумму для перевода!")
                        elif my_bal < amount:
                            async_send_message(chat_id, "❌ У вас недостаточно денег!")
                        else:
                            update_balance(user_id, -amount)
                            update_balance(target_id, amount)
                            async_send_message(
                                chat_id,
                                f"💸 **{first_name}** перевел **{amount}$** игроку **{target_name}**!",
                            )
                    else:
                        async_send_message(chat_id, "💡 Использование: ответьте на сообщение и напишите `/pay [сумма]`")

            # 2. Ограбление (/rob или ограбить)
            elif text_lower in ["ограбить", "/rob"]:
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя ограбить самого себя!")
                else:
                    curr_time = int(time.time())
                    cursor.execute("SELECT last_rob FROM users WHERE user_id = ?", (user_id,))
                    last_rob = cursor.fetchone()[0]

                    if curr_time - last_rob < 1800:
                        rem = 1800 - (curr_time - last_rob)
                        async_send_message(chat_id, f"⏳ Полиция ищет вас! Попробуйте через {int(rem // 60)} мин.")
                    else:
                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
                        target_row = cursor.fetchone()
                        target_bal = target_row[0] if target_row else 0

                        if target_bal < 100:
                            async_send_message(chat_id, f"❌ У {target_name} слишком мало денег в карманах!")
                        else:
                            cursor.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (curr_time, user_id))
                            conn.commit()

                            if random.random() < 0.5:
                                stolen = random.randint(50, min(target_bal, 1000))
                                update_balance(target_id, -stolen)
                                update_balance(user_id, stolen)
                                async_send_message(
                                    chat_id,
                                    f"🥷 **Успешное ограбление!** {first_name} выкрал **{stolen}$** у {target_name}!",
                                )
                            else:
                                fine = 200
                                update_balance(user_id, -fine)
                                async_send_message(
                                    chat_id,
                                    f"🚨 **Ограбление провалилось!** {first_name} попался полиции и заплатил штраф **{fine}$**.",
                                )

            # 3. Свадьба (/marry или брак)
            elif text_lower in ["брак", "/marry"]:
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя жениться на самом себе!")
                else:
                    cursor.execute("SELECT spouse_id FROM users WHERE user_id = ?", (user_id,))
                    my_spouse = cursor.fetchone()[0]

                    if my_spouse != 0:
                        async_send_message(chat_id, "❌ Вы уже состоите в браке!")
                    else:
                        cursor.execute("UPDATE users SET spouse_id = ? WHERE user_id = ?", (target_id, user_id))
                        cursor.execute("UPDATE users SET spouse_id = ? WHERE user_id = ?", (user_id, target_id))
                        conn.commit()

                        async_send_message(
                            chat_id,
                            f"💍 **ПОЗДРАВЛЯЕМ!** {first_name} и {target_name} теперь состоят в браке! 🎉",
                        )

            # 4. Дуэль (дуэль 500)
            elif text_lower.startswith("дуэль"):
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя вызвать на дуэль самого себя!")
                else:
                    parts = text.split()
                    if len(parts) >= 2:
                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                        my_bal = cursor.fetchone()[0]
                        bet = parse_amount(parts[1], my_bal)

                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
                        target_row = cursor.fetchone()
                        target_bal = target_row[0] if target_row else 0

                        if bet <= 0:
                            async_send_message(chat_id, "❌ Укажите корректную сумму ставки!")
                        elif my_bal < bet or target_bal < bet:
                            async_send_message(chat_id, "❌ У одного из участников недостаточно средств!")
                        else:
                            winner, loser = (user_id, target_id) if random.random() < 0.5 else (target_id, user_id)
                            winner_name = first_name if winner == user_id else target_name

                            update_balance(winner, bet)
                            update_balance(loser, -bet)

                            async_send_message(
                                chat_id,
                                f"⚔️ **ДУЭЛЬ!**\n\n"
                                f"💥 {first_name} и {target_name} сошлись в поединке на **{bet}$**!\n"
                                f"🏆 В жестоком бою победил **{winner_name}** и забирает банк **{bet * 2}$**!",
                            )

        # --- ТЕКСТОВЫЕ КОМАНДЫ И МЕНЮ ---
        if text.startswith("/start"):
            async_send_message(
                chat_id,
                f"🏰 **Добро пожаловать в RP Мир, {first_name}!**\n\n"
                f"⚠️ **ИНФОРМАЦИЯ О ПРОЕКТЕ:**\n"
                f"🛠 Бот находится на **стадии активной разработки**!\n"
                f"🤖 Некоторые идеи и решения были сгенерированы с помощью **ИИ**.\n\n"
                f"💡 Если вам интересно принять участие в проекте, предложить идеи или сообщить о баге — пишите разработчику: 👉 @Stariy_bog1336!\n\n"
                f"Ваш стартовый капитал: **1000$**.\nИспользуйте меню ниже для игры!",
                reply_markup=main_keyboard,
            )

        elif text_lower in ["🏦 банк", "банк", "/bank"] or text_lower.startswith(("банк ", "/bank ")):
            cursor.execute(
                "SELECT bank_balance, deposit_created, deposit_term_days, deposit_rate, balance, last_auto_interest FROM users WHERE user_id = ?",
                (user_id,),
            )
            bank_balance, dep_created, dep_term, dep_rate, my_balance, last_interest = cursor.fetchone()

            curr_time = int(time.time())

            if bank_balance > 0 and dep_created == 0:
                dep_created = curr_time
                cursor.execute(
                    "UPDATE users SET deposit_created = ?, last_auto_interest = ? WHERE user_id = ?",
                    (curr_time, curr_time, user_id)
                )
                conn.commit()

            if bank_balance > 0:
                last_check = last_interest if last_interest > 0 else dep_created
                rem_seconds = 3600 - (curr_time - last_check)
                if rem_seconds <= 0:
                    time_status = "доступно прямо сейчас!"
                else:
                    mins = int((rem_seconds % 3600) // 60)
                    time_status = f"через {mins} мин."

                status_text = f"✅ **Активен** (Доход {int(dep_rate * 100)}% {time_status})"
            else:
                status_text = "❌ **Нет средств на депозите**"

            bank_inline_kb = {
                "inline_keyboard": [
                    [
                        {"text": "📥 Положить на депозит", "callback_data": "bank_dep_prompt"},
                        {"text": "📤 Снять с депозита", "callback_data": "bank_wd_prompt"},
                    ]
                ]
            }

            async_send_message(
                chat_id,
                f"🏦 **Центральный Банк**\n\n"
                f"💼 Наличные в кармане: **{my_balance}$**\n"
                f"🏦 На депозите в банке: **{bank_balance}$**\n"
                f"📈 Начисление: **{int(dep_rate * 100)}% в час** (автоматически)\n"
                f"📊 Статус счета: {status_text}\n\n"
                f"Нажмите на кнопку ниже, чтобы внести или снять средства:",
                reply_markup=bank_inline_kb,
            )

        elif text == "🎰 Казино":
            async_send_message(
                chat_id,
                "🎰 **Казино и Азартные Игры**\n\nВыберите игру из меню ниже:",
                reply_markup=casino_menu_keyboard,
            )

        elif text in ["🏆 Топ богачей", "/top", "топ"]:
            cursor.execute(
                "SELECT first_name, (balance + bank_balance) as total FROM users ORDER BY total DESC LIMIT 10"
            )
            top_users = cursor.fetchall()

            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            top_text = "🏆 **ТОП-10 САМЫХ БОГАТЫХ ИГРОКОВ** 🏆\n\n"

            for i, (name, total) in enumerate(top_users):
                top_text += f"{medals[i]} {name} — {total}$\n"

            async_send_message(chat_id, top_text)

        elif text in ["ℹ️ Помощь / Команды", "/help", "помощь"]:
            async_send_message(
                chat_id,
                "📖 Справочное бюро\n\nВыберите нужную категорию из меню ниже:",
                reply_markup=help_keyboard,
            )

        elif text == "👤 Профиль":
            cursor.execute(
                "SELECT balance, job, spouse_id, house, car, bank_balance FROM users WHERE user_id = ?",
                (user_id,),
            )
            balance, job, spouse_id, house, car, bank_balance = cursor.fetchone()

            spouse_text = (
                f"💍 В браке с: {get_user_name(spouse_id)}"
                if spouse_id
                else "💍 Статус: Холост / Не замужем"
            )

            async_send_message(
                chat_id,
                f"👤 Ваш RP Профиль:\n\n"
                f"📝 Имя: {first_name}\n"
                f"💰 Наличные: {balance}$\n"
                f"🏦 На депозите: {bank_balance}$\n"
                f"💼 Работа: {job}\n"
                f"🏠 Дом: {house}\n"
                f"🚗 Автомобиль: {car}\n"
                f"{spouse_text}",
            )

        elif text == "🏰 Имущество":
            cursor.execute(
                "SELECT house, car, last_rent FROM users WHERE user_id = ?",
                (user_id,),
            )
            house, car, last_rent = cursor.fetchone()

            prop_buttons = [
                [{"text": "🏠 Купить недвижимость", "callback_data": "shop_houses"}],
                [{"text": "🚗 Купить автомобиль", "callback_data": "shop_cars"}],
            ]

            if house != "Отсутствует":
                prop_buttons.append(
                    [{"text": "💵 Собрать аренду с жильцов", "callback_data": "collect_rent"}]
                )

            async_send_message(
                chat_id,
                f"🏰 Рынок недвижимости и авто\n\n"
                f"Ваш дом: {house}\n"
                f"Ваш транспорт: {car}\n\n"
                f"Выберите категорию покупок:",
                reply_markup={"inline_keyboard": prop_buttons},
            )

        elif text == "💼 Работа":
            cursor.execute(
                "SELECT job, last_work FROM users WHERE user_id = ?", (user_id,)
            )
            job, last_work = cursor.fetchone()

            jobs_btn = [
                [
                    {
                        "text": f"Устроиться: {name} ({data['pay']}$/час)",
                        "callback_data": f"job_set_{name}",
                    }
                ]
                for name, data in JOBS.items()
            ]

            if job != "Безработный":
                jobs_btn.append(
                    [{"text": "🛠 Поработать (Получить ЗП)", "callback_data": "job_work"}]
                )

            async_send_message(
                chat_id,
                f"💼 Центр Занятости\n\n"
                f"Ваша текущая работа: {job}\n"
                f"Выберите вакансию или отработайте смену:",
                reply_markup={"inline_keyboard": jobs_btn},
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
                async_send_message(chat_id, "🎉 Вы получили ежедневный бонус 500$!")
            else:
                rem = 86400 - (curr_time - last_bonus)
                async_send_message(
                    chat_id,
                    f"⏳ Бонус доступен через {int(rem // 3600)} ч. {int((rem % 3600) // 60)} мин.",
                )

        elif text == "📺 Реклама (+300$)":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT last_ad FROM users WHERE user_id = ?", (user_id,)
            )
            last_ad = cursor.fetchone()[0]

            if curr_time - last_ad >= 3600:
                cursor.execute(
                    "UPDATE users SET balance = balance + 300, last_ad = ? WHERE user_id = ?",
                    (curr_time, user_id),
                )
                conn.commit()
                async_send_message(
                    chat_id, "📺 Спасибо за просмотр рекламы! Вам начислено +300$."
                )
            else:
                rem = 3600 - (curr_time - last_ad)
                async_send_message(
                    chat_id,
                    f"⏳ Следующий просмотр через {int((rem % 3600) // 60)} мин. {int(rem % 60)} сек.",
                )

    elif "callback_query" in update:
        call = update["callback_query"]
        chat_id = call["message"]["chat"]["id"]
        message_id = call["message"]["message_id"]
        data = call.get("data")

        if data == "help_about":
            async_edit_message_text(
                chat_id,
                message_id,
                "🛠 **Информация о разработке и ИИ:**\n\n"
                "• Бот находится в **активной стадии разработки** и постоянно улучшается.\n"
                "• Некоторые механики, идеи и фрагменты кода сгенерированы с помощью **ИИ**.\n\n"
                "👨‍💻 **Разработка и Сотрудничество:**\n"
                "Если хотите помочь проекту, предложить свою фичу или сообщили о баге:\n"
                "👉 Напишите разработчику: @Stariy_bog1336",
                reply_markup=back_to_help_kb,
            )

        elif data == "bank_dep_prompt":
            user_states[user_id] = {"action": "bank_deposit_amount"}
            async_send_message(chat_id, "🏦 **Введите сумму, которую хотите положить в банк** (или напишите `все`):")

        elif data == "bank_wd_prompt":
            user_states[user_id] = {"action": "bank_withdraw_amount"}
            async_send_message(chat_id, "🏦 **Введите сумму, которую хотите снять со счета** (или напишите `все`):")

        elif data == "play_roulette_menu":
            roulette_kb = {
                "inline_keyboard": [
                    [
                        {"text": "🔴 Красное (x2)", "callback_data": "roulette_sel_red"},
                        {"text": "⚫️ Чёрное (x2)", "callback_data": "roulette_sel_black"},
                    ],
                    [{"text": "🟢 Зеро (x14)", "callback_data": "roulette_sel_zero"}],
                ]
            }
            async_edit_message_text(chat_id, message_id, "🎰 **Рулетка**: Выберите исход для ставки:", reply_markup=roulette_kb)

        elif data.startswith("roulette_sel_"):
            choice = data.replace("roulette_sel_", "")
            user_states[user_id] = {"action": "roulette_bet_amount", "choice": choice}
            async_send_message(chat_id, f"🎰 **Вы выбрали {choice.upper()}**. Введите сумму ставки (или напишите `все`):")

        elif data == "play_21_prompt":
            user_states[user_id] = {"action": "21_bet_amount"}
            async_send_message(chat_id, "🃏 **Игра 21 (Блэкджек)**: Введите сумму ставки (или напишите `все`):")

        elif data == "play_dice_prompt":
            user_states[user_id] = {"action": "dice_bet_amount"}
            async_send_message(chat_id, "🎲 **Кости**: Введите сумму ставки (или напишите `все`):")

        elif data == "help_main":
            async_edit_message_text(
                chat_id,
                message_id,
                "📖 Справочное бюро\n\nВыберите нужную категорию из меню ниже:",
                reply_markup=help_keyboard,
            )

        elif data == "help_bank":
            async_edit_message_text(
                chat_id,
                message_id,
                "🏦 **Банк и Депозиты:**\n\n"
                "• Нажмите «🏦 Банк» -> «📥 Положить на депозит» и введите сумму.\n"
                "• Проценты (5% в час) начисляются **автоматически каждый час**!",
                reply_markup=back_to_help_kb,
            )

        elif data == "help_jobs":
            async_edit_message_text(
                chat_id,
                message_id,
                "💼 **Работа и Доход:**\n\n"
                "• Работа: Нажмите «💼 Работа», чтобы устроиться и получать зарплату каждый час.\n"
                "• Ежедневный бонус: Раз в 24 часа дает +500$.\n"
                "• Просмотр рекламы: Раз в час дает +300$.",
                reply_markup=back_to_help_kb,
            )

        elif data == "help_property":
            async_edit_message_text(
                chat_id,
                message_id,
                "🏰 **Имущество:**\n\n"
                "• Покупка: В разделе «🏰 Имущество» вы можете купить дома и авто.\n"
                "• Доход с аренды: Каждая квартира/дом приносит ежедневный пассивный доход от арендаторов!",
                reply_markup=back_to_help_kb,
            )

        elif data == "help_rp":
            async_edit_message_text(
                chat_id,
                message_id,
                "⚔️ **RP Взаимодействия (в чатах через Reply):**\n\n"
                "• Перевод: Ответьте на сообщение: `/pay [сумма]` или `дать 500`.\n"
                "• Ограбление: Ответьте на сообщение: `ограбить` или `/rob`.\n"
                "• Дуэль: Ответьте на сообщение: `дуэль [ставка]`.\n"
                "• Свадьба: Ответьте на сообщение: `Брак` или `/marry`.",
                reply_markup=back_to_help_kb,
            )

        elif data == "help_casino":
            async_edit_message_text(
                chat_id,
                message_id,
                "🎰 **Казино:**\n\n"
                "• Нажмите «🎰 Казино», выберите игру и введите желаемую сумму!",
                reply_markup=back_to_help_kb,
            )

        elif data == "shop_houses":
            h_buttons = [
                [
                    {
                        "text": f"{name} — {info['price']}$",
                        "callback_data": f"buy_h_{name}",
                    }
                ]
                for name, info in HOUSES.items()
            ]
            async_edit_message_text(
                chat_id,
                message_id,
                "🏠 Каталог недвижимости:\nПокупка приносит вам ежедневную аренду!",
                reply_markup={"inline_keyboard": h_buttons},
            )

        elif data == "shop_cars":
            c_buttons = [
                [
                    {
                        "text": f"{name} — {info['price']}$",
                        "callback_data": f"buy_c_{name}",
                    }
                ]
                for name, info in CARS.items()
            ]
            async_edit_message_text(
                chat_id,
                message_id,
                "🚗 Автосалон:\nВыберите автомобиль для покупки:",
                reply_markup={"inline_keyboard": c_buttons},
            )

        elif data.startswith("buy_h_"):
            h_name = data.replace("buy_h_", "")
            price = HOUSES[h_name]["price"]

            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()[0]

            if balance < price:
                async_answer_callback(call["id"], f"❌ Вам не хватает {price - balance}$!")
                return

            cursor.execute(
                "UPDATE users SET balance = balance - ?, house = ? WHERE user_id = ?",
                (price, h_name, user_id),
            )
            conn.commit()

            async_answer_callback(call["id"], f"🎉 Вы успешно купили {h_name}!")
            async_edit_message_text(
                chat_id, message_id, f"🎉 Поздравляем! Вы приобрели недвижимость: {h_name}!"
            )

        elif data.startswith("buy_c_"):
            c_name = data.replace("buy_c_", "")
            price = CARS[c_name]["price"]

            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()[0]

            if balance < price:
                async_answer_callback(call["id"], f"❌ Вам не хватает {price - balance}$!")
                return

            cursor.execute(
                "UPDATE users SET balance = balance - ?, car = ? WHERE user_id = ?",
                (price, c_name, user_id),
            )
            conn.commit()

            async_answer_callback(call["id"], f"🎉 Вы успешно купили {c_name}!")
            async_edit_message_text(
                chat_id, message_id, f"🎉 Поздравляем! Вы приобрели автомобиль: {c_name}!"
            )

        elif data == "collect_rent":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT house, last_rent FROM users WHERE user_id = ?", (user_id,)
            )
            house, last_rent = cursor.fetchone()

            if house == "Отсутствует":
                async_answer_callback(call["id"], "❌ У вас нет недвижимости!")
                return

            if curr_time - last_rent >= 86400:
                rent_amount = HOUSES[house]["rent"]
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, last_rent = ? WHERE user_id = ?",
                    (rent_amount, curr_time, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"💵 Вы собрали аренду: +{rent_amount}$!")
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"💵 Вы успешно собрали арендную плату с вашей недвижимости ({house}): +{rent_amount}$!",
                )
            else:
                rem = 86400 - (curr_time - last_rent)
                async_answer_callback(
                    call["id"],
                    f"⏳ Следующий сбор через {int(rem // 3600)} ч. {int((rem % 3600) // 60)} мин.",
                )

        elif data.startswith("job_set_"):
            new_job = data.replace("job_set_", "")
            cursor.execute(
                "UPDATE users SET job = ? WHERE user_id = ?", (new_job, user_id)
            )
            conn.commit()
            async_answer_callback(call["id"], f"🎉 Вы устроились на работу: {new_job}!")
            async_edit_message_text(
                chat_id,
                message_id,
                f"✅ Вы успешно устроились на работу: {new_job}!\nТеперь вы можете получать зарплату каждый час.",
            )

        elif data == "job_work":
            curr_time = int(time.time())
            cursor.execute(
                "SELECT job, last_work FROM users WHERE user_id = ?", (user_id,)
            )
            job, last_work = cursor.fetchone()

            if job == "Безработный":
                async_answer_callback(call["id"], "❌ Сначала устройтесь на работу!")
                return

            if curr_time - last_work >= 3600:
                pay = JOBS[job]["pay"]
                cursor.execute(
                    "UPDATE users SET balance = balance + ?, last_work = ? WHERE user_id = ?",
                    (pay, curr_time, user_id),
                )
                conn.commit()
                async_answer_callback(call["id"], f"💰 Вы отработали смену и получили {pay}$!")
                async_edit_message_text(
                    chat_id,
                    message_id,
                    f"⚙️ Вы успешно отработали смену на должности {job}!\n💵 Заработок: +{pay}$",
                )
            else:
                rem = 3600 - (curr_time - last_work)
                async_answer_callback(
                    call["id"],
                    f"⏳ Вы устали! Отдохните ещё {int((rem % 3600) // 60)} мин.",
                )

        elif data in ["21_hit", "21_stand"]:
            if user_id not in games_21:
                async_answer_callback(call["id"], "⚠️ Игра уже завершена!")
                return

            game = games_21[user_id]

            if data == "21_hit":
                game["player"].append(get_card())
                p_score = calculate_score(game["player"])

                if p_score > 21:
                    update_balance(user_id, -game["bet"])
                    async_edit_message_text(
                        chat_id,
                        message_id,
                        f"💥 Перебор! Ваши карты: {game['player']} ({p_score} очков).\nПроигрыш -{game['bet']}$.",
                    )
                    del games_21[user_id]
                else:
                    async_edit_message_text(
                        chat_id,
                        message_id,
                        f"Ваши карты: {game['player']} ({p_score} очков).\nВзять ещё или хватит?",
                        reply_markup=game21_keyboard,
                    )

            elif data == "21_stand":
                while calculate_score(game["dealer"]) < 17:
                    game["dealer"].append(get_card())

                p_score = calculate_score(game["player"])
                d_score = calculate_score(game["dealer"])

                text = f"🏁 Итоги:\nИгрок: {game['player']} ({p_score})\nДилер: {game['dealer']} ({d_score})\n\n"

                if d_score > 21 or p_score > d_score:
                    update_balance(user_id, game["bet"])
                    text += f"🎉 Вы выиграли +{game['bet']}$!"
                elif p_score < d_score:
                    update_balance(user_id, -game["bet"])
                    text += f"🔻 Вы проиграли -{game['bet']}$."
                else:
                    text += "🤝 Ничья!"

                async_edit_message_text(chat_id, message_id, text)
                del games_21[user_id]


# --- 5. ЗАПУСК БОТА ---
def main():
    api_request("deleteWebhook", {"drop_pending_updates": True})
    print("🚀 RP бот успешно запущен!")
    offset = 0

    while True:
        try:
            res = api_request("getUpdates", {"offset": offset, "timeout": 1})
            if res and res.get("ok"):
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    threading.Thread(target=handle_update, args=(update,), daemon=True).start()
        except Exception as e:
            print(f"Ошибка связи: {e}")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
