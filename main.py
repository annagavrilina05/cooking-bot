import sqlite3
import telebot
from telebot import types
import time
import threading
import re

bot = telebot.TeleBot('токен_бота')

# Подключение к базе данных
conn = sqlite3.connect('recipes.db', check_same_thread=False)
cursor = conn.cursor()

# Словарь для хранения избранных рецептов пользователей
favorites = {}

# Словарь для хранения активных таймеров
timers = {}


@bot.message_handler(commands=['start'])
def start(message):
    """
    Обработчик команды /start. Вызывает главное меню для пользователя.

    :param message: Объект сообщения, полученный от пользователя.
    """
    show_main_menu(message)


def show_main_menu(message):
    """
    Отправляет пользователю главное меню с вариантами выбора:
    "Рецепт из моих продуктов", "Рецепт по кухне", "Случайный рецепт", "Избранное".

    :param message: Объект сообщения, полученный от пользователя.
    """
    markup = types.ReplyKeyboardMarkup(row_width=2)
    item1 = types.KeyboardButton("Рецепт из моих продуктов")
    item2 = types.KeyboardButton("Рецепт по кухне")
    item3 = types.KeyboardButton("Случайный рецепт")
    item4 = types.KeyboardButton("Избранное")
    markup.add(item1, item2, item3, item4)
    bot.send_message(message.chat.id, "Привет! Я твой кулинарный помощник. Что ты хочешь сделать?", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "Рецепт из моих продуктов")
def my_ingredients(message):
    """
    Обработчик для выбора рецепта по имеющимся у пользователя продуктам.
    Удаляет клавиатуру и запрашивает ввод продуктов через запятую.

    :param message: Объект сообщения от пользователя.
    """
    markup = types.ReplyKeyboardRemove()
    msg = bot.send_message(message.chat.id, "Введите продукты через запятую:", reply_markup=markup)
    bot.register_next_step_handler(msg, find_recipes_by_ingredients)


def find_recipes_by_ingredients(message):
    """
    Выполняет поиск рецептов по введенным пользователем ингредиентам.
    Формирует SQL-запрос с использованием оператора LIKE для каждого ингредиента.

    :param message: Объект сообщения с текстом, содержащим ингредиенты, разделенные запятыми.
    """
    ingredients = [ingredient.strip().lower() for ingredient in message.text.split(',')]
    query = "SELECT * FROM recipes WHERE "
    # Поиск без учета порядка и регистра
    query += " AND ".join(["LOWER(ingredients) LIKE ?" for _ in ingredients])
    params = [f"%{ingredient}%" for ingredient in ingredients]
    cursor.execute(query, params)
    recipes = cursor.fetchall()
    if recipes:
        markup = types.ReplyKeyboardMarkup(row_width=2)
        for recipe in recipes[:4]:
            markup.add(types.KeyboardButton(recipe[1]))
        bot.send_message(message.chat.id, "Выберите рецепт:", reply_markup=markup)
        bot.register_next_step_handler(message, show_recipe_steps)
    else:
        bot.send_message(message.chat.id, "Рецепты не найдены.")
        show_main_menu(message)


def show_recipe_steps(message, from_favorites=False):
    """
    Отображает выбранный рецепт с возможностью добавления в избранное и установки таймера.

    :param message: Объект сообщения пользователя
    :param from_favorites: Флаг, указывающий, выбран ли рецепт из избранного
    """
    recipe_name = message.text
    cursor.execute("SELECT id, name, ingredients, steps FROM recipes WHERE name = ?", (recipe_name,))
    recipe = cursor.fetchone()
    if recipe:
        # Форматированный вывод рецепта
        response = f"**Название блюда:** {recipe[1]}\n\n**Ингредиенты:**\n{recipe[2]}\n\n**Этапы приготовления:**\n{recipe[3]}"
        # Создаем инлайн-кнопки
        markup = types.InlineKeyboardMarkup()
        if not from_favorites:
            add_to_favorites_button = types.InlineKeyboardButton("Добавить в избранное", callback_data=f"add_to_favorites_{recipe[0]}")
            markup.add(add_to_favorites_button)

        # Check for time intervals and add timer button if found
        time_intervals = extract_time_intervals(recipe[3])
        if time_intervals:
            timer_button = types.InlineKeyboardButton("Таймер", callback_data=f"timer_{recipe[0]}")
            markup.add(timer_button)

        next_button = types.InlineKeyboardButton("Дальше", callback_data="next")
        markup.add(next_button)
        bot.send_message(message.chat.id, response, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Рецепт не найден.")
        show_main_menu(message)


@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    """
    Обрабатывает нажатия инлайн-кнопок.

    :param call: Объект с информацией о кнопке
    """
    if call.data.startswith("add_to_favorites_"):
        recipe_id = int(call.data.split("_")[-1])
        if call.message.chat.id not in favorites:
            favorites[call.message.chat.id] = []
        if recipe_id not in favorites[call.message.chat.id]:
            favorites[call.message.chat.id].append(recipe_id)
            bot.answer_callback_query(call.id, "Рецепт добавлен в избранное!")
        else:
            bot.answer_callback_query(call.id, "Рецепт уже в избранном!")
    elif call.data == "next":
        show_main_menu(call.message)
    elif call.data.startswith("timer_"):
        recipe_id = int(call.data.split("_")[-1])
        cursor.execute("SELECT steps FROM recipes WHERE id = ?", (recipe_id,))
        steps = cursor.fetchone()[0]
        time_intervals = extract_time_intervals(steps)
        if time_intervals:
            markup = types.InlineKeyboardMarkup()
            for interval in time_intervals:
                markup.add(types.InlineKeyboardButton(interval, callback_data=f"start_timer_{interval}"))
            markup.add(types.InlineKeyboardButton("Отмена", callback_data="cancel_timer"))
            bot.send_message(call.message.chat.id, "Какой таймер поставить?", reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, "В рецепте не найдено временных интервалов.")
    elif call.data.startswith("start_timer_"):
        interval = call.data.split("_")[-1]
        duration = parse_time_interval(interval)
        if duration:
            chat_id = call.message.chat.id
            timers[chat_id] = {"duration": duration, "remaining": duration}
            start_timer(chat_id, duration)
            markup = types.InlineKeyboardMarkup()
            stop_button = types.InlineKeyboardButton("Остановить таймер", callback_data="stop_timer")
            markup.add(stop_button)
            bot.send_message(chat_id, f"Таймер на {interval} поставлен.", reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, "Не удалось распознать время.")
    elif call.data == "stop_timer":
        chat_id = call.message.chat.id
        if chat_id in timers:
            timers[chat_id]["remaining"] = 0
            bot.send_message(chat_id, "Таймер остановлен.")
    elif call.data == "cancel_timer":
        show_main_menu(call.message)


def extract_time_intervals(text):
    """
    Извлекает временные интервалы из текста рецепта.

    :param text: Строка с этапами приготовления
    :return: Список временных интервалов в формате строк (например, ["10 мин", "5 мин"])
    """
    return ['{} {}'.format(value, unit) for value, unit in re.findall(r'\((\d+(?:[.,]\d+)?)\s*(мин|ч)\)', text)]


def parse_time_interval(interval):
    """
    Преобразует строковый интервал времени в секунды.

    :param interval: Временной интервал (например, "10 мин" или "2 ч")
    :return: Длительность в секундах (например, 600 или 7200)
    """
    match = re.match(r'(\d+(?:[.,]\d+)?)\s*(мин|ч)', interval)
    if match:
        value_str, unit = match.groups()
        # Заменяем запятую на точку для корректного преобразования в число
        value = float(value_str.replace(',', '.'))
        # Умножаем на 60 или 3600 в зависимости от единицы времени
        return int(value * 60) if unit == 'мин' else int(value * 3600)
    return None


def start_timer(chat_id, duration):
    """
    Запускает таймер на указанную длительность.

    :param chat_id: ID чата пользователя
    :param duration: Длительность таймера в секундах
    """
    def timer():
        time.sleep(duration)
        if chat_id in timers and timers[chat_id]['remaining'] > 0:
            bot.send_message(chat_id, "Время вышло!")
            del timers[chat_id]
    threading.Thread(target=timer).start


@bot.message_handler(func=lambda message: message.text == "Рецепт по кухне")
def choose_cuisine(message):
    """
    Обработчик для выбора рецепта по кухне.
    Удаляет клавиатуру и запрашивает название кухни.

    :param message: Объект сообщения от пользователя.
    """
    markup = types.ReplyKeyboardRemove()
    msg = bot.send_message(message.chat.id, "Введите название кухни (например, итальянская, тайская и т.д.):", reply_markup=markup)
    bot.register_next_step_handler(msg, find_recipes_by_cuisine)

def find_recipes_by_cuisine(message):
    """
    Выполняет поиск рецептов по названию кухни.
    Выполняется SQL-запрос, который ищет точное совпадение названия кухни в нижнем регистре.

    :param message: Объект сообщения с введенным названием кухни.
    """
    cuisine = message.text.strip().lower()
    cursor.execute("SELECT * FROM recipes WHERE LOWER(cuisine) = ?", (cuisine,))
    recipes = cursor.fetchall()
    if recipes:
        markup = types.ReplyKeyboardMarkup(row_width=2)
        for recipe in recipes[:4]:
            markup.add(types.KeyboardButton(recipe[1]))
        bot.send_message(message.chat.id, "Выберите рецепт:", reply_markup=markup)
        bot.register_next_step_handler(message, show_recipe_steps)
    else:
        bot.send_message(message.chat.id, "Рецепты не найдены.")
        show_main_menu(message)


@bot.message_handler(func=lambda message: message.text == "Случайный рецепт")
def random_recipe(message):
    """
    Обработчик для выбора случайного рецепта.
    Из базы данных выбирается один рецепт в случайном порядке.

    :param message: Объект сообщения от пользователя.
    """
    cursor.execute("SELECT id, name, ingredients, steps FROM recipes ORDER BY RANDOM() LIMIT 1")
    recipe = cursor.fetchone()
    if recipe:
        # Форматированный вывод рецепта
        response = f"**Название блюда:** {recipe[1]}\n\n**Ингредиенты:**\n{recipe[2]}\n\n**Этапы приготовления:**\n{recipe[3]}"
        # Создаем инлайн-кнопки
        markup = types.InlineKeyboardMarkup()
        add_to_favorites_button = types.InlineKeyboardButton("Добавить в избранное", callback_data=f"add_to_favorites_{recipe[0]}")

        # Проверяем наличие временных интервалов для возможности установки таймера
        time_intervals = extract_time_intervals(recipe[3])
        if time_intervals:
            timer_button = types.InlineKeyboardButton("Таймер", callback_data=f"timer_{recipe[0]}")
            markup.add(timer_button)

        markup.add(add_to_favorites_button)
        next_button = types.InlineKeyboardButton("Дальше", callback_data="next")
        markup.add(next_button)
        bot.send_message(message.chat.id, response, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "Рецепты не найдены.")
        show_main_menu(message)


@bot.message_handler(func=lambda message: message.text == "Избранное")
def favorites_handler(message):
    """
    Обработчик для показа избранных рецептов пользователя.
    Получает список рецептов по их идентификаторам, сохраненным для данного чата, и выводит его.

    :param message: Объект сообщения от пользователя.
    """
    if message.chat.id in favorites and favorites[message.chat.id]:
        # Получаем названия рецептов из базы данных по их ID
        recipes_list = []
        for recipe_id in favorites[message.chat.id]:
            cursor.execute("SELECT name FROM recipes WHERE id = ?", (recipe_id,))
            recipe_name = cursor.fetchone()
            if recipe_name:
                recipes_list.append(recipe_name[0])
        # Формируем сообщение с пронумерованным списком рецептов
        if recipes_list:
            response = "Ваши избранные рецепты:\n" + "\n".join([f"{i+1}. {name}" for i, name in enumerate(recipes_list)])
            msg = bot.send_message(message.chat.id, response + "\nВведите номер рецепта, чтобы посмотреть его:")
            bot.register_next_step_handler(msg, lambda m: show_favorite_recipe_details(m, recipes_list))
        else:
            bot.send_message(message.chat.id, "У вас нет избранных рецептов.")
    else:
        bot.send_message(message.chat.id, "У вас нет избранных рецептов.")


def show_favorite_recipe_details(message, recipes_list):
    """
    Выводит подробности выбранного рецепта из избранного по номеру, введенному пользователем.

    :param message: Объект сообщения с номером выбранного рецепта.
    :param recipes_list: Список названий рецептов, сохраненных как избранное.
    """
    try:
        recipe_index = int(message.text) - 1  # Преобразуем ввод в индекс
        if 0 <= recipe_index < len(recipes_list):
            recipe_name = recipes_list[recipe_index]  # Получаем название рецепта
            cursor.execute("SELECT id, name, ingredients, steps FROM recipes WHERE name = ?", (recipe_name,))
            recipe = cursor.fetchone()
            if recipe:
                # Форматированный вывод рецепта
                response = f"**Название блюда:** {recipe[1]}\n\n**Ингредиенты:**\n{recipe[2]}\n\n**Этапы приготовления:**\n{recipe[3]}"
                # Создаем инлайн-кнопки
                markup = types.InlineKeyboardMarkup()

                # Check for time intervals and add timer button if found
                time_intervals = extract_time_intervals(recipe[3])
                if time_intervals:
                    timer_button = types.InlineKeyboardButton("Таймер", callback_data=f"timer_{recipe[0]}")
                    markup.add(timer_button)

                next_button = types.InlineKeyboardButton("Дальше", callback_data="next")
                markup.add(next_button)
                bot.send_message(message.chat.id, response, parse_mode="Markdown", reply_markup=markup)
            else:
                bot.send_message(message.chat.id, "Рецепт не найден.")
        else:
            bot.send_message(message.chat.id, "Неверный номер рецепта.")
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")


@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    """
    Обработчик для всех сообщений, не подходящих под другие обработчики.
    Выводит сообщение об ошибке и возвращает пользователя в главное меню.

    :param message: Объект сообщения от пользователя.
    """
    bot.send_message(message.chat.id, "Я не понял ваш запрос. Давайте начнем заново!")
    show_main_menu(message)

# Запуск бота
bot.polling(none_stop=True)
