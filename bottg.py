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

# --- 0. ФЕЙКОВЫЙ СЕРВЕР ДЛЯ РАБОТЫ НА БЕСПЛАТНОМ RENDER WEB SERVICE ---
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

games_21 = {}


# --- 2. СЕТЕВАЯ ОТПРАВКА ---
def api_request(method: str, params: dict = None):
    url = API_URL + method
    try:
        data = json.dumps(params).encode("utf-8") if params else None
        headers = {"Content-Type": "application/json"}
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


# --- 3. КОМПАКТНЫЕ КЛАВИАТУРЫ И КРАСИВОЕ МЕНЮ ---
# Внизу экрана оставляем только самые нужные кнопки, чтобы не было загромождения
main_bottom_keyboard = {
    "keyboard": [
        [{"text": "📱 Главное меню"}, {"text": "👤 Мой профиль"}],
        [{"text": "🎁 Ежедневный бонус"}, {"text": "ℹ️ Помощь"}],
    ],
    "resize_keyboard": True,
}

# Красивое интерактивное инлайн-меню
main_inline_menu = {
    "inline_keyboard": [
        [{"text": "🎰 Казино и Игры", "callback_data": "menu_casino"}, {"text": "💼 Работа и Заработок", "callback_data": "menu_jobs"}],
        [{"text": "🏦 Депозиты и Банк", "callback_data": "menu_bank"}, {"text": "🏰 Рынок Имущества", "callback_data": "menu_property"}],
        [{"text": "🏆 Топ богачей", "callback_data": "menu_top"}, {"text": "📺 Реклама (+300$)", "callback_data": "menu_ad"}],
    ]
}

back_to_main_kb = {
    "inline_keyboard": [[{"text": "⬅️ Назад в главное меню", "callback_data": "menu_main"}]]
}

help_keyboard = {
    "inline_keyboard": [
        [{"text": "🛠 О разработке и ИИ", "callback_data": "help_about"}],
        [{"text": "💼 Работа и Доход", "callback_data": "help_jobs"}, {"text": "🏦 Банк и Депозиты", "callback_data": "help_bank"}],
        [{"text": "🏰 Имущество и Дома", "callback_data": "help_property"}, {"text": "⚔️ Дуэли, Ограбления, Брак", "callback_data": "help_rp"}],
        [{"text": "🎰 Казино и Азарт", "callback_data": "help_casino"}],
        [{"text": "⬅️ Назад в главное меню", "callback_data": "menu_main"}],
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

game21_keyboard = {
    "inline_keyboard": [
        [{"text": "➕ Взять карту", "callback_data": "21_hit"}, {"text": "✋ Хватит", "callback_data": "21_stand"}]
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

        # Обработка ввода сумм
        if user_id in user_states and not text.startswith("/"):
            state = user_states[user_id]
            action = state["action"]

            cursor.execute("SELECT balance, bank_balance FROM users WHERE user_id = ?", (user_id,))
            my_balance, bank_balance = cursor.fetchone()

            if action == "bank_deposit_amount":
                amount = parse_amount(text, my_balance)
                del user_states[user_id]

                if amount <= 0 or my_balance < amount:
                    async_send_message(chat_id, "❌ Некорректная сумма или недостаточно наличных!")
                    return

                curr_time = int(time.time())
                cursor.execute(
                    "UPDATE users SET balance = balance - ?, bank_balance = bank_balance + ?, deposit_created = ?, deposit_rate = 0.05, last_auto_interest = ? WHERE user_id = ?",
                    (amount, amount, curr_time, curr_time, user_id),
                )
                conn.commit()

                async_send_message(
                    chat_id,
                    f"🏦 **Депозит пополнен!**\n💵 Внесено: **{amount}$**\n📈 Начисление: **5% в час**",
                )
                return

            elif action == "bank_withdraw_amount":
                amount = parse_amount(text, bank_balance)
                del user_states[user_id]

                if amount <= 0 or bank_balance < amount:
                    async_send_message(chat_id, "❌ Некорректная сумма или недостаточно средств в банке!")
                    return

                cursor.execute(
                    "UPDATE users SET balance = balance + ?, bank_balance = bank_balance - ? WHERE user_id = ?",
                    (amount, amount, user_id),
                )
                conn.commit()

                async_send_message(chat_id, f"🏦 Вы успешно сняли с депозита **{amount}$**!")
                return

            elif action == "roulette_bet_amount":
                choice = state["choice"]
                bet = parse_amount(text, my_balance)
                del user_states[user_id]

                if bet < 50 or my_balance < bet:
                    async_send_message(chat_id, "❌ Ставка от 50$ и не больше вашего баланса!")
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

                if bet < 100 or my_balance < bet:
                    async_send_message(chat_id, "❌ Ставка от 100$ и не больше вашего баланса!")
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

                if bet < 50 or my_balance < bet:
                    async_send_message(chat_id, "❌ Ставка от 50$ и не больше вашего баланса!")
                    return

                u_dice, b_dice = random.randint(1, 6) + random.randint(1, 6), random.randint(1, 6) + random.randint(1, 6)
                if u_dice > b_dice:
                    update_balance(user_id, bet)
                    res_msg = f"🏆 **ВЫ ВЫИГРАЛИ!** Вы получили +{bet}$!"
                elif u_dice < b_dice:
                    update_balance(user_id, -bet)
                    res_msg = f"💀 **ВЫ ПРОИГРАЛИ!** Потеряно -{bet}$."
                else:
                    res_msg = "🤝 **НИЧЬЯ!** Ставка возвращена."

                async_send_message(
                    chat_id,
                    f"🎲 **Бросок костей (Ставка: {bet}$)**\n🎯 Ваши: **{u_dice}** | 🤖 Бот: **{b_dice}**\n\n{res_msg}",
                )
                return

        # RP-Команды через ответом на сообщение (Reply)
        reply_to = msg.get("reply_to_message")
        if reply_to:
            target_id = reply_to["from"]["id"]
            target_name = reply_to["from"].get("first_name", "Игрок")

            if text_lower.startswith(("/pay", "дать", "передать")):
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя переводить самому себе!")
                else:
                    get_user(target_id, target_name)
                    parts = text.split()
                    if len(parts) >= 2:
                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
                        my_bal = cursor.fetchone()[0]
                        amount = parse_amount(parts[1], my_bal)

                        if amount <= 0 or my_bal < amount:
                            async_send_message(chat_id, "❌ Некорректная сумма или недостаточно денег!")
                        else:
                            update_balance(user_id, -amount)
                            update_balance(target_id, amount)
                            async_send_message(chat_id, f"💸 **{first_name}** перевел **{amount}$** игроку **{target_name}**!")

            elif text_lower in ["ограбить", "/rob"]:
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя ограбить самого себя!")
                else:
                    curr_time = int(time.time())
                    cursor.execute("SELECT last_rob FROM users WHERE user_id = ?", (user_id,))
                    last_rob = cursor.fetchone()[0]

                    if curr_time - last_rob < 1800:
                        rem = 1800 - (curr_time - last_rob)
                        async_send_message(chat_id, f"⏳ Перезарядка! Попробуйте через {int(rem // 60)} мин.")
                    else:
                        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (target_id,))
                        target_row = cursor.fetchone()
                        target_bal = target_row[0] if target_row else 0

                        if target_bal < 100:
                            async_send_message(chat_id, f"❌ У {target_name} нет денег в карманах!")
                        else:
                            cursor.execute("UPDATE users SET last_rob = ? WHERE user_id = ?", (curr_time, user_id))
                            conn.commit()

                            if random.random() < 0.5:
                                stolen = random.randint(50, min(target_bal, 1000))
                                update_balance(target_id, -stolen)
                                update_balance(user_id, stolen)
                                async_send_message(chat_id, f"🥷 **Успешно!** {first_name} украл **{stolen}$** у {target_name}!")
                            else:
                                fine = 200
                                update_balance(user_id, -fine)
                                async_send_message(chat_id, f"🚨 **Провал!** {first_name} попался полиции и заплатил штраф {fine}$.")

            elif text_lower in ["брак", "/marry"]:
                if target_id == user_id:
                    async_send_message(chat_id, "❌ Нельзя вступить в брак с самим собой!")
                else:
                    cursor.execute("SELECT spouse_id FROM users WHERE user_id = ?", (user_id,))
                    if cursor.fetchone()[0] != 0:
                        async_send_message(chat_id, "❌ Вы уже состоите в браке!")
                    else:
                        cursor.execute("UPDATE users SET spouse_id = ? WHERE user_id = ?", (target_id, user_id))
                        cursor.execute("UPDATE users SET spouse_id = ? WHERE user_id = ?", (user_id, target_id))
                        conn.commit()
                        async_send_message(chat_id, f"💍 **ПОЗДРАВЛЯЕМ!** {first_name} и {target_name} теперь в браке! 🎉")

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

                        if bet <= 0 or my_bal < bet or target_bal < bet:
                            async_send_message(chat_id, "❌ Недостаточно средств у одного из участников!")
                        else:
                            winner, loser = (user_id, target_id) if random.random() < 0.5 else (target_id, user_id)
                            winner_name = first_name if winner == user_id else target_name

                            update_balance(winner, bet)
                            update_balance(loser, -bet)
                            async_send_message(
                                chat_id,
                                f"⚔️ **ДУЭЛЬ!**\n💥 {first_name} и {target_name} бились на **{bet}$**!\n🏆 Победил **{winner_name}**!",
                            )

        # Текстовые кнопки
        if text.startswith("/start") or text == "📱 Главное меню":
            async_send_message(
                chat_id,
                f"🏰 **Добро пожаловать в RP Мир, {first_name}!**\n\nВыберите нужный раздел из интерактивного меню ниже:",
                reply_markup=main_bottom_keyboard,
            )
            async_send_message(chat_id, "👇 **Интерактивное меню:**", reply_markup=main_inline_menu)

        elif text in ["👤 Мой профиль", "/profile", "профиль"]:
            cursor.execute("SELECT balance, job, spouse_id, house, car, bank_balance FROM users WHERE user_id = ?", (user_id,))
            balance, job, spouse_id, house, car, bank_balance = cursor.fetchone()
            spouse_text = f"💍 В браке с: {get_user_name(spouse_id)}" if spouse_id else "💍 Статус: Холост"

            async_send_message(
                chat_id,
                f"👤 **Ваш RP Профиль:**\n\n"
                f"📝 Имя: {first_name}\n"
                f"💰 Наличные: **{balance}$**\n"
                f"🏦 В банке: **{bank_balance}$**\n"
                f"💼 Работа: **{job}**\n"
                f"🏠 Дом: **{house}**\n"
                f"🚗 Авто: **{car}**\n"
                f"{spouse_text}",
            )

        elif text in ["ℹ️ Помощь", "/help", "помощь"]:
            async_send_message(chat_id, "📖 **Справочное бюро**\n\nВыберите категорию знаний:", reply_markup=help_keyboard)

        elif text == "🎁 Ежедневный бонус":
            curr_time = int(time.time())
            cursor.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
            last_bonus = cursor.fetchone()[0]

            if curr_time - last_bonus >= 86400:
                cursor.execute("UPDATE users SET balance = balance + 500, last_bonus = ? WHERE user_id = ?", (curr_time, user_id))
                conn.commit()
                async_send_message(chat_id, "🎉 Вы получили ежедневный бонус **+500$**!")
            else:
                rem = 86400 - (curr_time - last_bonus)
                async_send_message(chat_id, f"⏳ До следующего бонуса: {int(rem // 3600)} ч. {int((rem % 3600) // 60)} мин.")

    # Обработка кликов по инлайн-кнопкам
    elif "callback_query" in update:
        call = update["callback_query"]
        chat_id = call["message"]["chat"]["id"]
        message_id = call["message"]["message_id"]
        data = call.get("data")

        if data == "menu_main":
            async_edit_message_text(chat_id, message_id, "👇 **Главное интерактивное меню:**", reply_markup=main_inline_menu)

        elif data == "menu_casino":
            async_edit_message_text(chat_id, message_id, "🎰 **Казино и Азартные Игры**\n\nВыберите игру:", reply_markup=casino_menu_keyboard)

        elif data == "menu_bank":
            cursor.execute("SELECT bank_balance, deposit_rate, balance FROM users WHERE user_id = ?", (user_id,))
            bank_balance, dep_rate, my_balance = cursor.fetchone()

            bank_inline_kb = {
                "inline_keyboard": [
                    [{"text": "📥 Внести депозит", "callback_data": "bank_dep_prompt"}, {"text": "out Снять со счета", "callback_data": "bank_wd_prompt"}],
                    [{"text": "⬅️ Назад", "callback_data": "menu_main"}],
                ]
            }
            async_edit_message_text(
                chat_id,
                message_id,
                f"🏦 **Центральный Банк**\n\n💵 Наличные: **{my_balance}$**\n🏦 На депозите: **{bank_balance}$**\n📈 Ставка: **{int(dep_rate * 100)}% в час**",
                reply_markup=bank_inline_kb,
            )

        elif data == "menu_jobs":
            cursor.execute("SELECT job FROM users WHERE user_id = ?", (user_id,))
            job = cursor.fetchone()[0]

            jobs_btn = [[{"text": f"Устроиться: {name} ({data['pay']}$/ч)", "callback_data": f"job_set_{name}"}] for name, data in JOBS.items()]
            if job != "Безработный":
                jobs_btn.append([{"text": "🛠 Поработать (Собрать ЗП)", "callback_data": "job_work"}])
            jobs_btn.append([{"text": "⬅️ Назад", "callback_data": "menu_main"}])

            async_edit_message_text(
                chat_id, message_id, f"💼 **Центр Занятости**\n\nТекущая работа: **{job}**", reply_markup={"inline_keyboard": jobs_btn}
            )

        elif data == "menu_property":
            cursor.execute("SELECT house, car FROM users WHERE user_id = ?", (user_id,))
            house, car = cursor.fetchone()

            prop_buttons = [
                [{"text": "🏠 Купить дом", "callback_data": "shop_houses"}, {"text": "🚗 Купить авто", "callback_data": "shop_cars"}]
            ]
            if house != "Отсутствует":
                prop_buttons.append([{"text": "💵 Собрать аренду с жильцов", "callback_data": "collect_rent"}])
            prop_buttons.append([{"text": "⬅️ Назад", "callback_data": "menu_main"}])

            async_edit_message_text(
                chat_id,
                message_id,
                f"🏰 **Рынок Имущества**\n\nВаш дом: **{house}**\nВаше авто: **{car}**",
                reply_markup={"inline_keyboard": prop_buttons},
            )

        elif data == "menu_top":
            cursor.execute("SELECT first_name, (balance + bank_balance) as total FROM users ORDER BY total DESC LIMIT 10")
            top_users = cursor.fetchall()

            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            top_text = "🏆 **ТОП-10 САМЫХ БОГАТЫХ ИГРОКОВ** 🏆\n\n"
            for i, (name, total) in enumerate(top_users):
                top_text += f"{medals[i]} {name} — {total}$\n"

            async_edit_message_text(chat_id, message_id, top_text, reply_markup=back_to_main_kb)

        elif data == "menu_ad":
            curr_time = int(time.time())
            cursor.execute("SELECT last_ad FROM users WHERE user_id = ?", (user_id,))
            last_ad = cursor.fetchone()[0]

            if curr_time - last_ad >= 3600:
                cursor.execute("UPDATE users SET balance = balance + 300, last_ad = ? WHERE user_id = ?", (curr_time, user_id))
                conn.commit()
                async_answer_callback(call["id"], "📺 Спасибо за просмотр! Вам начислено +300$")
            else:
                rem = 3600 - (curr_time - last_ad)
                async_answer_callback(call["id"], f"⏳ Просмотр через {int((rem % 3600) // 60)} мин.")

        # Дополнительные callback-команды
        elif data == "help_about":
            async_edit_message_text(
                chat_id,
                message_id,
                "🛠 **Разработка и ИИ:**\n• Бот постоянно дорабатывается.\n• Идеи и механики генерируются с помощью ИИ.\n\n👨‍💻 Связь с разработчиком: @Stariy_bog1336",
                reply_markup=back_to_main_kb,
            )

        elif data == "help_jobs":
            async_edit_message_text(chat_id, message_id, "💼 **Работа:** Каждый час вы можете собирать зарплату в Меню -> Работа.", reply_markup=back_to_main_kb)

        elif data == "help_bank":
            async_edit_message_text(chat_id, message_id, "🏦 **Банк:** Депозит приносит 5% в час автоматически!", reply_markup=back_to_main_kb)

        elif data == "help_property":
            async_edit_message_text(chat_id, message_id, "🏰 **Имущество:** Дома и авто дают престиж и ежедневный доход от аренды.", reply_markup=back_to_main_kb)

        elif data == "help_rp":
            async_edit_message_text(
                chat_id,
                message_id,
                "⚔️ **RP Команды в чатах (через Reply на сообщение):**\n• `/pay 500` или `дать 500` — Перевести деньги\n• `ограбить` или `/rob` — Ограбить игрока\n• `дуэль 500` — Вызвать на дуэль\n• `брак` или `/marry` — Вступить в брак",
                reply_markup=back_to_main_kb,
            )

        elif data == "help_casino":
            async_edit_message_text(chat_id, message_id, "🎰 **Казино:** Сыграйте в Рулетку, 21 или Кости в разделе Казино!", reply_markup=back_to_main_kb)

        elif data == "bank_dep_prompt":
            user_states[user_id] = {"action": "bank_deposit_amount"}
            async_send_message(chat_id, "🏦 Введите сумму для взноса на депозит (или `все`):")

        elif data == "bank_wd_prompt":
            user_states[user_id] = {"action": "bank_withdraw_amount"}
            async_send_message(chat_id, "🏦 Введите сумму для снятия с депозита (или `все`):")

        elif data == "play_roulette_menu":
            roulette_kb = {
                "inline_keyboard": [
                    [{"text": "🔴 Красное (x2)", "callback_data": "roulette_sel_red"}, {"text": "⚫️ Чёрное (x2)", "callback_data": "roulette_sel_black"}],
                    [{"text": "🟢 Зеро (x14)", "callback_data": "roulette_sel_zero"}],
                    [{"text": "⬅️ Назад", "callback_data": "menu_casino"}],
                ]
            }
            async_edit_message_text(chat_id, message_id, "🎰 **Рулетка:** Выберите вариант исхода:", reply_markup=roulette_kb)

        elif data.startswith("roulette_sel_"):
            choice = data.replace("roulette_sel_", "")
            user_states[user_id] = {"action": "roulette_bet_amount", "choice": choice}
            async_send_message(chat_id, f"🎰 Вы выбрали **{choice.upper()}**. Введите сумму ставки (от 50$ или `все`):")

        elif data == "play_21_prompt":
            user_states[user_id] = {"action": "21_bet_amount"}
            async_send_message(chat_id, "🃏 **Игра 21:** Введите сумму ставки (от 100$ или `все`):")

        elif data == "play_dice_prompt":
            user_states[user_id] = {"action": "dice_bet_amount"}
            async_send_message(chat_id, "🎲 **Кости:** Введите сумму ставки (от 50$ или `все`):")

        elif data == "shop_houses":
            h_buttons = [[{"text": f"{name} — {info['price']}$", "callback_data": f"buy_h_{name}"}] for name, info in HOUSES.items()]
            h_buttons.append([{"text": "⬅️ Назад", "callback_data": "menu_property"}])
            async_edit_message_text(chat_id, message_id, "🏠 **Каталог недвижимости:**", reply_markup={"inline_keyboard": h_buttons})

        elif data == "shop_cars":
            c_buttons = [[{"text": f"{name} — {info['price']}$", "callback_data": f"buy_c_{name}"}] for name, info in CARS.items()]
            c_buttons.append([{"text": "⬅️ Назад", "callback_data": "menu_property"}])
            async_edit_message_text(chat_id, message_id, "🚗 **Автосалон:**", reply_markup={"inline_keyboard": c_buttons})

        elif data.startswith("buy_h_"):
            h_name = data.replace("buy_h_", "")
            price = HOUSES[h_name]["price"]
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()[0]

            if balance < price:
                async_answer_callback(call["id"], f"❌ Не хватает {price - balance}$!")
            else:
                cursor.execute("UPDATE users SET balance = balance - ?, house = ? WHERE user_id = ?", (price, h_name, user_id))
                conn.commit()
                async_answer_callback(call["id"], f"🎉 Куплено: {h_name}!")
                async_edit_message_text(chat_id, message_id, f"🎉 Поздравляем! Вы приобрели дом **{h_name}**!", reply_markup=back_to_main_kb)

        elif data.startswith("buy_c_"):
            c_name = data.replace("buy_c_", "")
            price = CARS[c_name]["price"]
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            balance = cursor.fetchone()[0]

            if balance < price:
                async_answer_callback(call["id"], f"❌ Не хватает {price - balance}$!")
            else:
                cursor.execute("UPDATE users SET balance = balance - ?, car = ? WHERE user_id = ?", (price, c_name, user_id))
                conn.commit()
                async_answer_callback(call["id"], f"🎉 Куплено: {c_name}!")
                async_edit_message_text(chat_id, message_id, f"🎉 Поздравляем! Вы приобрели авто **{c_name}**!", reply_markup=back_to_main_kb)

        elif data == "collect_rent":
            curr_time = int(time.time())
            cursor.execute("SELECT house, last_rent FROM users WHERE user_id = ?", (user_id,))
            house, last_rent = cursor.fetchone()

            if house == "Отсутствует":
                async_answer_callback(call["id"], "❌ У вас нет недвижимости!")
            elif curr_time - last_rent >= 86400:
                rent_amount = HOUSES[house]["rent"]
                cursor.execute("UPDATE users SET balance = balance + ?, last_rent = ? WHERE user_id = ?", (rent_amount, curr_time, user_id))
                conn.commit()
                async_answer_callback(call["id"], f"💵 Собрано: +{rent_amount}$!")
            else:
                rem = 86400 - (curr_time - last_rent)
                async_answer_callback(call["id"], f"⏳ Следующий сбор через {int(rem // 3600)} ч.")

        elif data.startswith("job_set_"):
            new_job = data.replace("job_set_", "")
            cursor.execute("UPDATE users SET job = ? WHERE user_id = ?", (new_job, user_id))
            conn.commit()
            async_answer_callback(call["id"], f"🎉 Новая работа: {new_job}")
            async_edit_message_text(chat_id, message_id, f"✅ Вы успешно устроились: **{new_job}**!", reply_markup=back_to_main_kb)

        elif data == "job_work":
            curr_time = int(time.time())
            cursor.execute("SELECT job, last_work FROM users WHERE user_id = ?", (user_id,))
            job, last_work = cursor.fetchone()

            if job == "Безработный":
                async_answer_callback(call["id"], "❌ Устройтесь на работу!")
            elif curr_time - last_work >= 3600:
                pay = JOBS[job]["pay"]
                cursor.execute("UPDATE users SET balance = balance + ?, last_work = ? WHERE user_id = ?", (pay, curr_time, user_id))
                conn.commit()
                async_answer_callback(call["id"], f"💰 Зарплата получена: +{pay}$")
            else:
                rem = 3600 - (curr_time - last_work)
                async_answer_callback(call["id"], f"⏳ Отдых ещё {int((rem % 3600) // 60)} мин.")

        elif data in ["21_hit", "21_stand"]:
            if user_id not in games_21:
                async_answer_callback(call["id"], "⚠️ Игра завершена!")
                return

            game = games_21[user_id]
            if data == "21_hit":
                game["player"].append(get_card())
                p_score = calculate_score(game["player"])

                if p_score > 21:
                    update_balance(user_id, -game["bet"])
                    async_edit_message_text(chat_id, message_id, f"💥 Перебор ({p_score} очков)! Вы проиграли -{game['bet']}$.", reply_markup=back_to_main_kb)
                    del games_21[user_id]
                else:
                    async_edit_message_text(
                        chat_id, message_id, f"Ваши карты: {game['player']} ({p_score} очков).\nВзять ещё или хватит?", reply_markup=game21_keyboard
                    )

            elif data == "21_stand":
                while calculate_score(game["dealer"]) < 17:
                    game["dealer"].append(get_card())

                p_score, d_score = calculate_score(game["player"]), calculate_score(game["dealer"])
                res_text = f"🏁 **Результаты 21:**\nВы: {game['player']} ({p_score})\nДилер: {game['dealer']} ({d_score})\n\n"

                if d_score > 21 or p_score > d_score:
                    update_balance(user_id, game["bet"])
                    res_text += f"🎉 Вы выиграли **+{game['bet']}$**!"
                elif p_score < d_score:
                    update_balance(user_id, -game["bet"])
                    res_text += f"🔻 Вы проиграли **-{game['bet']}$**."
                else:
                    res_text += "🤝 Ничья!"

                async_edit_message_text(chat_id, message_id, res_text, reply_markup=back_to_main_kb)
                del games_21[user_id]


# --- 5. ЗАПУСК БОТА ---
def main():
    api_request("deleteWebhook", {"drop_pending_updates": True})
    print("🚀 Бот с красивым интерактивным меню запущен!")
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
