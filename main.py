import os
import requests
import pandas as pd
import time

API_KEY = os.environ.get("NOVA_POSHTA_API_KEY", "").strip()

def get_np_status(ttn_number):
    if not API_KEY:
        return "Немає NOVA_POSHTA_API_KEY у змінних середовища"
    url = "https://api.novaposhta.ua/v2.0/json/"
    payload = {
        "apiKey": API_KEY,
        "modelName": "TrackingDocument",
        "calledMethod": "getStatusDocuments",
        "methodProperties": {
            "Documents": [{"DocumentNumber": ttn_number}]
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        data = response.json()
        if data['success'] and len(data['data']) > 0:
            return data['data'][0]['Status']
        else:
            return "Помилка номера"
    except Exception as e:
        return f"Помилка: {e}"

def process_excel():
    print("📂 Відкриваю файл orders.xlsx...")
    
    try:
        # Відкриваємо файл. dtype=str важливо, щоб номери не псувалися
        df = pd.read_excel("orders.xlsx", dtype=str)
    except FileNotFoundError:
        print("❌ Файл orders.xlsx не знайдено! Переконайтеся, що він у тій самій папці.")
        return

    # Перевіряємо назву колонки
    if 'Номер ТТН' not in df.columns:
        print("❌ Не знайдено колонку 'Номер ТТН'. Перевірте назву в першому рядку Excel.")
        return

    print(f"🔍 Знайдено {len(df)} рядків. Починаю перевірку...\n")

    # Проходимо по всіх рядках
    for index, row in df.iterrows():
        ttn = str(row['Номер ТТН'])
        
        # Перевіряємо тільки якщо це схоже на ТТН (14 цифр), ігноруємо пусті рядки
        if len(ttn) == 14 and ttn.isdigit():
            print(f"Перевіряю {ttn}...", end=" ")
            
            # Отримуємо статус
            status = get_np_status(ttn)
            
            # Записуємо у колонку 'Статус НП'
            df.at[index, 'Статус НП'] = status
            print(f"✅ {status}")
            
            time.sleep(0.1) # Пауза, щоб не блокувати сервер
        else:
            continue

    # Зберігаємо результат
    df.to_excel("orders.xlsx", index=False)
    print("\n💾 Готово! Файл orders.xlsx оновлено.")

if __name__ == "__main__":
    process_excel()
