from flask import jsonify, render_template, request
from services import get_lockers, get_route
# try:
#     # Prefer new agent-based service when available
from chat_service_v4 import handle_chat
# except Exception:
#     # Fallback to legacy implementation

from config import NAVER_MAP_KEY

def register_routes(app):
    @app.route('/')
    def index():
        return render_template('index.html', naver_map_key=NAVER_MAP_KEY)

    @app.route('/api/route')
    def route_api():
        start = request.args.get('start') # lat,lng
        end = request.args.get('end')     # lat,lng
        mode = request.args.get('mode', 'transit') # transit or car
        sub_mode = request.args.get('sub_mode') # subway or bus

        result = get_route(start, end, mode, sub_mode)
        if isinstance(result, tuple):  # error case
            return jsonify(result[0]), result[1]
        return jsonify(result)

    @app.route('/api/lockers')
    def lockers_api():
        result = get_lockers()
        if isinstance(result, tuple):  # error case
            return jsonify(result[0]), result[1]
        return jsonify(result)

    @app.route('/api/chat', methods=['POST'])
    def chat_api():
        data = request.json
        user_message = data.get('message', '')
        trip_context = data.get('tripData', []) # Receive current plan context

        lang = data.get('lang', 'ko')
        result = handle_chat(user_message, trip_context, lang)
        return jsonify(result)