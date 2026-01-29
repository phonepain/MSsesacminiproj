import json
import requests
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.tools import tool
from services import get_route, get_lockers

# # --- 벡터 DB 및 리트리버 설정 ---
# embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
# vectorstore = Chroma(embedding_function=embedding_model, persist_directory="./tour_db")
# retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

# --- 1. 벡터 DB 및 리트리버 설정 ---
embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(embedding_function=embedding_model, persist_directory="./tour_db")

# --- 2. [신규] RAG 데이터 전처리 함수 ---
def process_rag_docs(docs):
    """RAG 데이터의 lon 필드를 lng로 변환하고 유니코드를 정제합니다."""
    cleaned = []
    for d in docs:
        content = d.page_content
        try:
            if "\\u" in content:
                content = content.encode('utf-8').decode('unicode_escape')
        except: pass

        metadata = d.metadata.copy()
        # 데이터의 'lon'을 프론트엔드와 길찾기 API 규격인 'lng'로 매핑
        if 'lon' in metadata:
            metadata['lng'] = metadata.pop('lon')
            
        cleaned.append({"content": content[:500], "metadata": metadata})
    return json.dumps(cleaned, ensure_ascii=False)

# --- 3. [신규] 카테고리별 세분화 도구 ---

@tool
def attraction_search_tool(query: str):
    """서울의 박물관, 미술관, 테마 거리, 관광 명소 정보를 검색합니다."""
    # museum_art와 tourism_street 카테고리 필터링
    retriever = vectorstore.as_retriever(search_kwargs={
        "k": 5, 
        "filter": {"category": {"$in": ["museum_art", "tourism_street"]}}
    })
    return process_rag_docs(retriever.invoke(query))

@tool
def market_search_tool(query: str):
    """서울의 전통시장, 맛집 골목 정보를 검색합니다."""
    # traditional_market 카테고리 필터링
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5, "filter": {"category": "traditional_market"}})
    return process_rag_docs(retriever.invoke(query))

@tool
def station_search_tool(query: str):
    """서울 및 수도권 지하철역의 위치 정보를 검색합니다."""
    # subway_station 카테고리 필터링
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3, "filter": {"category": "subway_station"}})
    return process_rag_docs(retriever.invoke(query))

# @tool
# def convenience_search_tool(query: str):
#     """화장실, 관광안내소 등 여행 편의시설 정보를 검색합니다."""
#     # public_toilet과 tourist_info_center 카테고리 필터링
#     retriever = vectorstore.as_retriever(search_kwargs={
#         "k": 5, 
#         "filter": {"category": {"$in": ["public_toilet", "tourist_info_center"]}}
#     })
#     return process_rag_docs(retriever.invoke(query))

@tool
def vector_search_tool(query: str):
    """서울 관광지 정보, 맛집, 이용 시간 및 API 명세 문서를 검색합니다."""
    retriever = vectorstore.as_retriever(search_kwargs={
        "k": 5, "filter": {"category": {"$in": ["museum_art", "tourism_street","traditional_market"]}}})
    docs = retriever.invoke(query)
    
    # 디버깅용 로그: 유니코드 깨짐 방지를 위해 직접 한글로 출력 시도
    print(f"\n🔍 [RAG 검색 쿼리]: {query}")
    
    cleaned_results = []
    for i, d in enumerate(docs):
        # 1. 유니코드 이스케이프 문자열(\uc788...)이 들어있을 경우 실제 한글로 변환
        content = d.page_content
        try:
            # 리터럴 문자열로 저장된 경우 디코딩 시도
            if "\\u" in content:
                content = content.encode('utf-8').decode('unicode_escape')
        except Exception:
            pass # 변환 실패 시 원본 유지

        # 2. 너무 긴 내용은 토큰 절약을 위해 잘라내기
        # 검색 결과 1개당 약 500자 정도로 제한하는 것이 효율적입니다.
        summarized_content = content[:500] 
        
        print(f"   - 검색 결과 {i+1} (정제됨): {summarized_content[:30]}...")
        
        cleaned_results.append({
            "content": summarized_content,
            "metadata": d.metadata
        })
    
    # ensure_ascii=False로 설정하여 LLM에게 한글 원문을 그대로 전달합니다.
    return json.dumps(cleaned_results, ensure_ascii=False)
#tool.py 내 route_tool 예시
# @tool
# def route_tool(start: str, end: str):
#     """
#     두 지점 사이의 경로를 검색하는 도구입니다.
#     입력값: start(위도,경도), end(위도,경도)
#     """
#     try:
#         # 1. API 호출 (타임아웃 설정 권장)
#         response = requests.get(
#             f"http://localhost:5000/api/route?start={start}&end={end}",
#             timeout=10
#         )
        
#         # 2. HTTP 상태 코드 확인 (404, 500 등 방지)
#         response.raise_for_status()

#         # 3. 빈 응답(Empty Body) 체크 - 질문하신 에러의 핵심 원인 해결
#         if not response.text.strip():
#             return "시스템 알림: 경로 검색 결과가 비어 있습니다. 좌표가 유효한지 확인하세요."

#         # 4. JSON 파싱 시도
#         try:
#             data = response.json()
#             # 한글이 깨지지 않도록 직렬화하여 반환
#             return json.dumps(data, ensure_ascii=False)
#         except json.JSONDecodeError:
#             # JSON이 아닌 HTML 에러 페이지 등이 왔을 때 처리
#             return f"시스템 알림: 서버 응답 형식이 올바르지 않습니다. (응답 내용: {response.text[:100]})"

#     except requests.exceptions.RequestException as e:
#         # 네트워크 연결 문제나 서버가 꺼져 있을 때
#         return f"시스템 알림: API 서버 연결 실패. 서버가 실행 중인지 확인하세요. (에러: {str(e)})"
#     except Exception as e:
#         # 기타 예상치 못한 모든 에러 처리
#         return f"시스템 알림: 예기치 못한 오류가 발생했습니다. ({str(e)})"
    
# @tool
# def lockers_tool(_query: str = ""):
#     """서울 주요 지하철역 및 관광지의 물품 보관소 위치와 현황을 조회합니다."""
#     return json.dumps(get_lockers(), ensure_ascii=False)





# 다른 파일에서 불러오기 쉽게 리스트로 묶어줍니다.
tools = [
    attraction_search_tool, 
    market_search_tool, 
    station_search_tool,
    vector_search_tool, 
    # convenience_search_tool, 
    #route_tool, lockers_tool]
]
