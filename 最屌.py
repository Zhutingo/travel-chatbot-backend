import re
import json
import requests
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate

# === API Key 設定 ===
GOOGLE_API_KEY = "AIzaSyDLexfRnQxJ0ez4Ks8jdZa80FBd0_bDl7s"
OPENWEATHER_API_KEY = "2234ac8b70af23220667096f300a1e64"

# === 模型與 Prompt ===
model = OllamaLLM(model="llama3")

prompt = ChatPromptTemplate.from_template("""
你是一個台灣智慧旅遊小幫手，擅長以親切自然的繁體中文與使用者互動。

{chat_history}

請根據對話判斷：
1. 問附近美食、景點、去哪玩，回傳 {{ "action": "search_places", "location": "地點", "query_type": "美食/景點/咖啡廳" }}
2. 問天氣，回傳 {{ "action": "weather", "location": "城市" }}
3. 問一日遊行程，回傳 {{ "action": "plan_trip", "location": "城市" }}
4. 問怎麼走、導航、如何到達，回傳 {{ "action": "directions", "origin": "起點", "destination": "終點" }}

⚠️ 符合以上分類只回JSON，否則自然回覆。

使用者問題：{question}
""")

chain = prompt | model

# === 工具方法 ===
def safe_json_parse(text):
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return None

def fix_action_typo(action):
    return {"wether": "weather", "whether": "weather", "searchplace": "search_places", "plantrip": "plan_trip"}.get(action.lower(), action)

def detect_english(text):
    return bool(re.search(r'[a-zA-Z]', text))

def detect_followup(text):
    followup_phrases = ["還有嗎", "再推薦", "更多", "繼續"]
    return any(phrase in text for phrase in followup_phrases)

# === API 呼叫 ===
def get_weather(city):
    geo_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={city}&key={GOOGLE_API_KEY}"
    try:
        geo_resp = requests.get(geo_url, timeout=5).json()
        if geo_resp.get("status") != "OK":
            return "❗ 找不到該地區位置"
        location = geo_resp["results"][0]["geometry"]["location"]
        lat, lng = location["lat"], location["lng"]

        weather_url = f"http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={OPENWEATHER_API_KEY}&units=metric&lang=zh_tw"
        weather_resp = requests.get(weather_url, timeout=5).json()
        if weather_resp.get("cod") != 200:
            return f"❗ 天氣查詢失敗：{weather_resp.get('message', '')}"
        desc = weather_resp['weather'][0]['description']
        temp = weather_resp['main']['temp']
        return f"🌦 {city}現在天氣：{desc}，氣溫：{temp:.1f}°C"
    except Exception as e:
        return f"⚠️ 天氣API錯誤：{e}"

def geocode_location_with_radius(location):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={location}&key={GOOGLE_API_KEY}"
    resp = requests.get(url).json()
    if resp.get("status") != "OK":
        return None, None, 1000

    loc = resp["results"][0]["geometry"]["location"]
    components = resp["results"][0].get("address_components", [])
    types = [t for comp in components for t in comp["types"]]

    if "locality" in types or "administrative_area_level_1" in types:
        radius = 5000
    else:
        radius = 1000

    return loc["lat"], loc["lng"], radius

def search_google_places(location, query_type="景點", all_results=False):
    TYPE_MAPPING = {
        "景點": "tourist_attraction",
        "美食": "restaurant",
        "咖啡廳": "cafe"
    }
    place_type = TYPE_MAPPING.get(query_type, "tourist_attraction")

    lat, lng, radius = geocode_location_with_radius(location)
    if lat is None or lng is None:
        return []

    url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lng}&radius={radius}&type={place_type}&key={GOOGLE_API_KEY}&language=zh-TW"
    try:
        response = requests.get(url, timeout=5).json()
        if response.get("status") != "OK":
            return []
        results = response.get("results", [])
        return results
    except Exception as e:
        return []

def format_places(results, start_idx=0, count=5):
    sliced = results[start_idx:start_idx+count]
    if not sliced:
        return "❗ 沒有更多推薦了喔"
    return "\n\n".join([
        f"📍 {place['name']}\n📌 地址：{place.get('vicinity', '地址未知')}\n⭐️ 評分：{place.get('rating', '無評分')}\n🕒 營業狀態：{'營業中' if place.get('opening_hours', {}).get('open_now') else '休息中或無資料'}\n🔗 地圖連結：https://maps.google.com/?q={place['geometry']['location']['lat']},{place['geometry']['location']['lng']}"
        for place in sliced
    ])

def plan_trip(location):
    return f"✨ {location}一日遊推薦：\n上午：景點參觀 ➡️ 下午：老街小吃 ➡️ 晚上：夜市吃透透"

def get_directions(origin, destination):
    url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination={destination}&mode=transit&key={GOOGLE_API_KEY}&language=zh-TW"
    try:
        resp = requests.get(url, timeout=5).json()
        if resp["status"] != "OK":
            return f"❗ 路線查詢失敗：{resp.get('status','')}"
        steps = resp["routes"][0]["legs"][0]["steps"]
        return "🛤 路線建議：\n" + "\n".join(re.sub('<[^>]+>', '', s["html_instructions"]) for s in steps)
    except:
        return "⚠️ 路線API錯誤"

# === 主對話流程 ===
last_search = {"location": None, "query_type": None, "results": [], "current_index": 0}

def handle_conversation():
    print("👋 歡迎使用旅遊AI助手，輸入 exit 離開")
    qa_history = []
    last_city = None

    while True:
        user_input = input("你：")
        if user_input.lower() == "exit":
            print("👋 感謝使用，祝你旅途愉快！")
            break

        if detect_english(user_input):
            print("⚠️ 請用繁體中文輸入喔！")
            continue

        if detect_followup(user_input) and last_search["results"]:
            start_idx = last_search["current_index"]
            answer = format_places(last_search["results"], start_idx)
            last_search["current_index"] += 5
            print("\n", answer)
            qa_history.append((user_input, answer))
            continue

        chat_history = "".join([f"你：{q}\nAI：{a}\n" for q,a in qa_history])
        response = chain.invoke({"chat_history": chat_history, "question": user_input})
        data = safe_json_parse(response)

        if data:
            action = fix_action_typo(data.get("action", ""))
            try:
                if action == "weather":
                    location = data.get("location", last_city or "台北")
                    last_city = location
                    answer = get_weather(location)
                elif action == "search_places":
                    location = data.get("location", last_city or "台北")
                    query_type = data.get("query_type", "景點")
                    last_city = location
                    results = search_google_places(location, query_type)
                    last_search.update({"location": location, "query_type": query_type, "results": results, "current_index": 5})
                    answer = format_places(results, 0)
                elif action == "plan_trip":
                    location = data.get("location", last_city or "台北")
                    last_city = location
                    answer = plan_trip(location)
                elif action == "directions":
                    origin = data.get("origin", last_city or "台北")
                    destination = data.get("destination", "台北101")
                    answer = get_directions(origin, destination)
                else:
                    answer = "🤖 無法辨識需求，請再說清楚一點喔！"
            except Exception as e:
                answer = f"⚠️ 執行錯誤：{e}"
        else:
            answer = response

        print("\n", answer)
        qa_history.append((user_input, answer))

if __name__ == "__main__":
    handle_conversation()
