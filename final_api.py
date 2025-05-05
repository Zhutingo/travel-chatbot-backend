from flask import Flask, request, jsonify
from 最屌 import chain, safe_json_parse, fix_action_typo, get_weather, search_google_places, format_places, plan_trip, get_directions

app = Flask(__name__)
qa_history = []
last_search = {"location": None, "query_type": None, "results": [], "current_index": 0}
last_city = "台北"

@app.route('/chat', methods=['POST'])
def chat():
    global qa_history, last_search, last_city
    user_input = request.json.get("message", "")
    
    if not user_input:
        return jsonify({"reply": "請輸入訊息"}), 400

    chat_history = "".join([f"你：{q}\nAI：{a}\n" for q, a in qa_history])
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

    qa_history.append((user_input, answer))
    return jsonify({"reply": answer})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
