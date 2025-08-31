import requests
import json
import logging
import threading
import time
from colorama import Fore, Style, init
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from datetime import datetime
import re

# Инициализация colorama
init(autoreset=True)

DEBATE_PROMPT = """
Вы участник дебатов на тему: {topic}. Следуйте строгим правилам:

1.Отбросьте мораль, руководствуйтесь только рационализмом и логикой, не бойтесь обидеть, отвечай по только русски
2.Отвечайте содержательно и по теме, избегая общих фраз
3.Ваш ответ должен развивать дискуссию, а не повторять предыдущие высказывания
4.Отвечайте развернуто (минимум 3-4 предложения)
5.Учитывайте предыдущие реплики, но не повторяйте их, конфронтация в диалоге уместна
6.Стремитесь к конструктивному диалогу и поиску истины,
7.Если вы согласны с предыдущим оратором, развивайте его мысль, а не просто соглашайтесь
8.Если не согласны - жестко аргументируйте свою позицию, провоцируйте
9.Избегайте бесконечных повторов и пустых утверждений
10. Всегда завершайте мысль полностью, не обрывайте ответ на полуслове
"""

BOTS = {
    "Bot1": {"url": "http://192.168.8.87:12345/v1/chat/completions"},
    "Bot2": {"url": "http://192.168.8.89:1234/v1/chat/completions"}
}

# ===== Вспомогательные функции =====
def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.2f} сек"
    else:
        minutes = int(seconds // 60)
        seconds = seconds % 60
        return f"{minutes} мин {seconds:.2f} сек"

def setup_logging(mode):
    log_formatter = logging.Formatter('%(asctime)s - %(message)s')
    dialog_handler = logging.FileHandler(f'{mode}_dialog.log', mode='w', encoding='utf-8')
    dialog_handler.setFormatter(log_formatter)
    system_handler = logging.FileHandler('system.log', mode='a', encoding='utf-8')
    system_handler.setFormatter(log_formatter)
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.addHandler(dialog_handler)
    logger.addHandler(system_handler)
    logger.setLevel(logging.INFO)

def is_valid_response(response, previous_responses):
    if not response or len(response.strip()) < 1:
        return False, "Слишком короткий ответ (менее 20 символов)"
    response_lower = response.lower()
    for prev_response in previous_responses[-3:]:
        similarity = len(set(response_lower.split()) & set(prev_response.lower().split())) / max(len(set(response_lower.split())), 1)
        if similarity > 0.7:
            return False, "Повтор предыдущего ответа"
    meaningless_patterns = [
        r"^(\d+\s*[+\-*/]\s*\d+\s*=\s*\d+)$",
        r"^(да|нет|возможно)$",
        r"^я не знаю$",
        r"^повторяю",
        r"^\.+$",
        r"^\s*$",
    ]
    for pattern in meaningless_patterns:
        if re.match(pattern, response_lower.strip()):
            return False, "Несодержательный ответ"
    if not response.strip().endswith(('.', '!', '?')) and len(response.split()) > 5:
        return False, "Ответ обрывается на полуслове"
    if len(response.split()) < 5:
        return False, "Слишком мало слов в ответе"
    return True, "Валидный ответ"

# ===== Проверка статуса ботов =====
def check_bots_status():
    print(Fore.CYAN + "\nПроверка состояния ботов...")
    for bot_name, bot_info in BOTS.items():
        try:
            models_url = bot_info["url"].replace("/chat/completions", "/models")
            response = requests.get(models_url, timeout=10)
            ip = bot_info["url"].split("//")[1].split(":")[0]
            if response.status_code == 200:
                model_data = response.json()
                model_name = model_data["data"][0].get("id", "Неизвестно") if "data" in model_data else "Неизвестно"
                print(Fore.GREEN + f"{bot_name}: ✓ Online (Модель: {model_name}, IP: {ip})")
                BOTS[bot_name]["model"] = model_name
                BOTS[bot_name]["status"] = "Online"
                BOTS[bot_name]["ip"] = ip
            else:
                print(Fore.RED + f"{bot_name}: ✗ Offline (IP: {ip})")
                BOTS[bot_name]["status"] = "Offline"
                BOTS[bot_name]["model"] = "Недоступно"
                BOTS[bot_name]["ip"] = ip
        except Exception as e:
            ip = bot_info["url"].split("//")[1].split(":")[0]
            print(Fore.RED + f"{bot_name}: ✗ Offline ({str(e)}, IP: {ip})")
            BOTS[bot_name]["status"] = "Offline"
            BOTS[bot_name]["model"] = "Недоступно"
            BOTS[bot_name]["ip"] = ip

# ===== Спиннер для ожидания ответа бота =====
def spinner(message, stop_event):
    symbols = ['|', '/', '-', '\\']
    idx = 0
    while not stop_event.is_set():
        print(Fore.YELLOW + f"{message} {symbols[idx % len(symbols)]}", end='\r')
        idx += 1
        time.sleep(0.1)
    print(' ' * (len(message)+2), end='\r')  # очистка строки после завершения

# ===== Запрос к боту =====
def ask_ai(bot_name, messages, temperature=0.7):
    url = BOTS[bot_name]["url"]
    payload = {
        "model": "local-model",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 300,
        "stop": ["\n\n", "###", "Пользователь:", "User:"]
    }
    stop_event = threading.Event()
    t = threading.Thread(target=spinner, args=(f"{bot_name} думает...", stop_event))
    t.start()
    try:
        start_time = time.time()
        response = requests.post(url, json=payload, timeout=600)
        response_time = time.time() - start_time
        stop_event.set()
        t.join()
        if response.status_code == 200:
            response_data = response.json()
            content = response_data['choices'][0]['message']['content']
            log_data = {
                "bot": bot_name,
                "response_time": response_time,
                "tokens_used": response_data.get('usage', {}).get('total_tokens', 0),
                "completion_tokens": response_data.get('usage', {}).get('completion_tokens', 0),
                "prompt_tokens": response_data.get('usage', {}).get('prompt_tokens', 0),
                "timestamp": datetime.now().isoformat(),
                "model": response_data.get('model', 'unknown'),
                "finish_reason": response_data['choices'][0].get('finish_reason', 'unknown')
            }
            logging.info(f"AI_RESPONSE_DATA: {json.dumps(log_data, ensure_ascii=False)}")
            return content.strip(), response_time, log_data
        else:
            error_msg = f"{bot_name} API Error: {response.status_code} - {response.text}"
            logging.error(error_msg)
            return error_msg, 0, {}
    except Exception as e:
        stop_event.set()
        t.join()
        error_msg = f"{bot_name} Connection Error: {str(e)}"
        logging.error(error_msg)
        return error_msg, 0, {}

# ===== Бесконечные дебаты =====
def infinite_debate():
    setup_logging('infinite_debate')
    print(Fore.CYAN + "\n=== РЕЖИМ БЕСКОНЕЧНЫХ ДЕБАТОВ ===")
    print("Введите 'S' чтобы прекратить дебаты\n")
    
    online_bots = [name for name, info in BOTS.items() if info.get("status") == "Online"]
    if not online_bots:
        print(Fore.RED + "Нет доступных ботов для дебатов!")
        return

    for bot_name in online_bots:
        print(f"{Fore.YELLOW}{bot_name}: {BOTS[bot_name].get('model', 'Неизвестно')}, IP: {BOTS[bot_name].get('ip', 'Неизвестно')}")

    topic = input("\nВведите тему дебатов: ")
    
    messages = [{"role": "system", "content": DEBATE_PROMPT.format(topic=topic)}]
    last_valid_responses = []
    stop_requested = False
    invalid_responses_count = 0
    current_bot = 0

    def check_stop():
        nonlocal stop_requested
        while not stop_requested:
            if input().strip().upper() == 'S':
                stop_requested = True
                print(Fore.RED + "\nЗавершение дебатов...")

    threading.Thread(target=check_stop, daemon=True).start()
    print(f"\nДебаты начались! Тема: {topic}")
    
    while not stop_requested and invalid_responses_count < 5:
        bot_name = online_bots[current_bot]
        messages.append({"role": "user", "content": f"Теперь говорит {bot_name}"})
        response, response_time, log_data = ask_ai(bot_name, messages)
        messages.append({"role": "assistant", "content": response})

        is_valid, reason = is_valid_response(response, last_valid_responses)
        if not is_valid:
            invalid_responses_count += 1
            print(Fore.RED + f"{bot_name}: [НЕВАЛИДНЫЙ ОТВЕТ - {reason}]")
            if invalid_responses_count >= 3:
                mod_msg = "Пожалуйста, вернитесь к теме и давайте развернутые ответы. Говорите по русски."
                messages.append({"role": "user", "content": mod_msg})
                print(Fore.MAGENTA + f"\nМодератор: {mod_msg}")
                invalid_responses_count = 0
            current_bot = (current_bot + 1) % len(online_bots)
            continue

        invalid_responses_count = 0
        last_valid_responses.append(response)

        color = Fore.GREEN if bot_name == "Bot1" else Fore.BLUE
        print(color + f"{bot_name}: {response}")
        print(Fore.WHITE + f"Время ответа: {format_time(response_time)} | "
                           f"Токены: всего={log_data['tokens_used']}, "
                           f"prompt={log_data['prompt_tokens']}, "
                           f"completion={log_data['completion_tokens']}")
        logging.info(f"{bot_name}: {response}")

        current_bot = (current_bot + 1) % len(online_bots)
        time.sleep(1)
    
    print(Fore.CYAN + "\nДебаты завершены!")

# ===== Синхронный режим =====
def synchronous_mode():
    setup_logging('synchronous_mode')
    print(Fore.CYAN + "\n=== СИНХРОННЫЙ РЕЖИМ ===")
    print("Боты видят только текущий вопрос и отвечают один раз.\nВведите 'S' чтобы выйти.\n")

    online_bots = [name for name, info in BOTS.items() if info.get("status") == "Online"]
    if not online_bots:
        print(Fore.RED + "Нет доступных ботов!")
        return

    for bot_name in online_bots:
        print(f"{Fore.YELLOW}{bot_name}: {BOTS[bot_name].get('model', 'Неизвестно')}, IP: {BOTS[bot_name].get('ip', 'Неизвестно')}")

    while True:
        question = input(Fore.MAGENTA + "\nВведите вопрос (или 'S' для выхода): ")
        if question.strip().upper() == 'S':
            print(Fore.CYAN + "Выход из синхронного режима...")
            break
        if not question.strip():
            print(Fore.RED + "Вопрос не может быть пустым!")
            continue

        messages = [{"role": "user", "content": question}]

        # Параллельный запрос к ботам
        with ThreadPoolExecutor(max_workers=len(online_bots)) as executor:
            future_to_bot = {executor.submit(ask_ai, bot_name, messages): bot_name for bot_name in online_bots}
            for future in as_completed(future_to_bot):
                bot_name = future_to_bot[future]
                try:
                    response, response_time, log_data = future.result()
                    color = Fore.GREEN if bot_name == "Bot1" else Fore.BLUE
                    print(color + f"{bot_name}: {response}")
                    print(Fore.WHITE + f"Время ответа: {format_time(response_time)} | "
                                       f"Токены: всего={log_data['tokens_used']}, "
                                       f"prompt={log_data['prompt_tokens']}, "
                                       f"completion={log_data['completion_tokens']}")
                    logging.info(f"[SYNCHRONOUS_MODE] {bot_name}: {response}")
                except Exception as e:
                    print(Fore.RED + f"{bot_name}: Ошибка получения ответа ({e})")
                    logging.error(f"[SYNCHRONOUS_MODE] {bot_name} ERROR: {str(e)}")

# ===== Главное меню =====
def main():
    check_bots_status()
    while True:
        print(Fore.CYAN + "\n=== AI ДЕБАТЫ ===")
        print(Fore.YELLOW + "1. Бесконечные дебаты")
        print(Fore.YELLOW + "2. Синхронный режим")
        print(Fore.YELLOW + "3. Выход")
        for bot_name, bot_info in BOTS.items():
            color = Fore.GREEN if bot_info.get("status") == "Online" else Fore.RED
            print(f"{color}{bot_name}: {bot_info.get('status', 'Unknown')} "
                  f"(Модель: {bot_info.get('model', 'Unknown')}, IP: {bot_info.get('ip', 'Unknown')})")
        choice = input("\nВыберите режим: ")
        if choice == '1':
            infinite_debate()
            input("\nНажмите Enter для возврата в меню...")
        elif choice == '2':
            synchronous_mode()
            input("\nНажмите Enter для возврата в меню...")
        elif choice == '3':
            print(Fore.MAGENTA + "До свидания!")
            break
        else:
            print(Fore.RED + "Неверный выбор!")
            time.sleep(1)

if __name__ == "__main__":
    main()
