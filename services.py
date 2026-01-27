import requests
import json
from config import SERVICE_KEY, BASE_URL, STDG_CD, ODSAY_API_KEY, NAVER_MAP_KEY, NAVER_CLIENT_SECRET

def get_lockers():
    """물품보관함 정보 + 실시간 현황 통합 API"""
    try:
        # 1. 위치 정보 가져오기
        info_response = requests.get(
            f'{BASE_URL}/locker_info',
            params={
                'serviceKey': SERVICE_KEY,
                'pageNo': 1,
                'numOfRows': 500,
                'type': 'json',
                'stdgCd': STDG_CD
            },
            timeout=10
        )
        info_data = info_response.json()

        # 2. 실시간 현황 가져오기
        realtime_response = requests.get(
            f'{BASE_URL}/locker_realtime_use',
            params={
                'serviceKey': SERVICE_KEY,
                'pageNo': 1,
                'numOfRows': 500,
                'type': 'json',
                'stdgCd': STDG_CD
            },
            timeout=10
        )
        realtime_data = realtime_response.json()

        # 3. 데이터 통합
        if (info_data.get('header', {}).get('resultCode') != 'K0' or
            realtime_data.get('header', {}).get('resultCode') != 'K0'):
            return {'error': 'API 응답 오류'}, 500

        info_items = info_data.get('body', {}).get('item', [])
        realtime_items = realtime_data.get('body', {}).get('item', [])

        # stlckId를 키로 하는 딕셔너리 생성
        realtime_dict = {item['stlckId']: item for item in realtime_items}

        # 통합 데이터 생성
        lockers = []
        for info in info_items:
            locker_id = info['stlckId']
            realtime = realtime_dict.get(locker_id, {})

            lockers.append({
                'id': locker_id,
                'name': info.get('stlckRprsPstnNm', ''),
                'detail': info.get('stlckDtlPstnNm', ''),
                'lat': float(info.get('lat', 0)),
                'lng': float(info.get('lot', 0)),
                'address': info.get('fcltRoadNmAddr', ''),
                'large': {
                    'available': int(realtime.get('usePsbltyLrgszStlckCnt', 0))
                },
                'medium': {
                    'available': int(realtime.get('usePsbltyMdmszStlckCnt', 0))
                },
                'small': {
                    'available': int(realtime.get('usePsbltySmlszStlckCnt', 0))
                },
                'totalCount': int(info.get('stlckCnt', 0)),
                'operatingHours': f"{info.get('wkdyOperBgngTm', '')[:2]}:{info.get('wkdyOperBgngTm', '')[2:4]} - {info.get('wkdyOperEndTm', '')[:2]}:{info.get('wkdyOperEndTm', '')[2:4]}",
                'updateTime': realtime.get('totDt', '')
            })

        return {
            'success': True,
            'count': len(lockers),
            'lockers': lockers
        }

    except Exception as e:
        return {'error': str(e)}, 500

def get_route(start, end, mode, sub_mode):
    if not start or not end:
        return {'error': 'Missing start or end coordinates'}, 400

    path_data = []

    try:
        start_lat, start_lng = map(float, start.split(','))
        end_lat, end_lng = map(float, end.split(','))

        # TRANSIT MODE (ODsay API)
        if mode == 'transit' and ODSAY_API_KEY:
            # Map sub_mode to SearchPathType
            # 0: All, 1: Subway, 2: Bus
            path_type = 0
            if sub_mode == 'subway':
                path_type = 1
            elif sub_mode == 'bus':
                path_type = 2

            # ODsay SearchPubTransPath (Standard)
            url = "https://api.odsay.com/v1/api/searchPubTransPath"
            params = {
                "SX": start_lng,
                "SY": start_lat,
                "EX": end_lng,
                "EY": end_lat,
                "apiKey": ODSAY_API_KEY,
                "SearchPathType": path_type
            }

            headers = {"Referer": "http://localhost:5000"}
            response = requests.get(url, params=params, headers=headers)
            if response.status_code == 200:
                res_json = response.json()
                if 'result' in res_json and 'path' in res_json['result']:
                    best_path = res_json['result']['path'][0]
                    sub_paths = []

                    # Store current location to handle walking segments
                    current_loc = [start_lat, start_lng]

                    for sub in best_path.get('subPath', []):
                        sub_data = {
                            "trafficType": sub.get('trafficType'), # 1:Subway, 2:Bus, 3:Walk
                            "path": [],
                            "stations": []
                        }

                        # Get stations
                        pass_stations = sub.get('passStopList', {}).get('stations', [])
                        for st in pass_stations:
                            sub_data["stations"].append({
                                "name": st.get('stationName'),
                                "lat": float(st.get('y')),
                                "lng": float(st.get('x'))
                            })

                        # 1. Start with the current_loc for this segment
                        sub_data["path"].append(current_loc)

                        # 2. Get detailed path for transit (Subway/Bus)
                        detailed_path_found = False
                        if sub.get('trafficType') in [1, 2]:
                            for lane in sub.get('lane', []):
                                map_obj = lane.get('mapObj', '')
                                if map_obj:
                                    clean_map_obj = map_obj if '@' in map_obj else f"0:0@{map_obj}"
                                    lane_url = "https://api.odsay.com/v1/api/loadLane"
                                    lane_params = {"apiKey": ODSAY_API_KEY, "mapObject": clean_map_obj}
                                    lane_res = requests.get(lane_url, params=lane_params, headers=headers)
                                    if lane_res.status_code == 200:
                                        lane_json = lane_res.json()
                                        for l in lane_json.get('result', {}).get('lane', []):
                                            for section in l.get('section', []):
                                                for pos in section.get('graphPos', []):
                                                    coord = [pos['y'], pos['x']]
                                                    if not sub_data["path"] or sub_data["path"][-1] != coord:
                                                        sub_data["path"].append(coord)
                                        detailed_path_found = True

                        # 3. Fallback: Use stations if detailed path failed or it's a walking segment
                        if not detailed_path_found or sub.get('trafficType') == 3:
                            for st in sub_data["stations"]:
                                coord = [st['lat'], st['lng']]
                                if not sub_data["path"] or sub_data["path"][-1] != coord:
                                    sub_data["path"].append(coord)

                        # Add end location of segment to current_loc for next segment
                        if sub_data["stations"]:
                            current_loc = [sub_data["stations"][-1]['lat'], sub_data["stations"][-1]['lng']]

                        sub_paths.append(sub_data)

                    # Final correction: ensure segments connect
                    for i in range(len(sub_paths)):
                        if len(sub_paths[i]["path"]) == 1:
                            if i < len(sub_paths) - 1:
                                next_start = sub_paths[i+1]["path"][0]
                                sub_paths[i]["path"].append(next_start)
                            else:
                                sub_paths[i]["path"].append([end_lat, end_lng])

                    return {
                        'success': True,
                        'subPaths': sub_paths,
                        'mode': mode
                    }

            # If ODsay failed or no path found, fallback will happen below
            if not path_data:
                print("ODsay API failed or no path found, Falling back to Driving API")

        # CAR MODE (Naver Directions API) or fallback for transit
        if not path_data:
            client_id = NAVER_MAP_KEY
            client_secret = NAVER_CLIENT_SECRET

            if client_id and client_secret:
                headers = {
                    "X-NCP-APIGW-API-KEY-ID": client_id,
                    "X-NCP-APIGW-API-KEY": client_secret
                }

                url = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
                params = {
                    "start": f"{start_lng},{start_lat}", # lng,lat
                    "goal": f"{end_lng},{end_lat}",     # lng,lat
                    "option": "traoptimal"
                }

                response = requests.get(url, headers=headers, params=params)

                if response.status_code == 200:
                    res_json = response.json()
                    if res_json and 'route' in res_json and 'traoptimal' in res_json['route']:
                        raw_path = res_json['route']['traoptimal'][0]['path']
                        path_data = [[p[1], p[0]] for p in raw_path]

        # Absolute Fallback (Straight Line)
        if not path_data:
            path_data = [[start_lat, start_lng], [end_lat, end_lng]]

        return {
            'success': True,
            'path': path_data,
            'mode': mode
        }
    except Exception as e:
        print(f"Routing Error: {e}")
        return {'error': str(e)}, 500