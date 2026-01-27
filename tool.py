import json
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.tools import tool
from services import get_route, get_lockers

# --- 벡터 DB 및 리트리버 설정 ---
embedding_model = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma(embedding_function=embedding_model, persist_directory="./tour_db")
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

@tool
def vector_search_tool(query: str):
    """서울 관광지 정보, 맛집, 이용 시간 및 API 명세 문서를 검색합니다."""
    docs = retriever.invoke(query)
    print(f"\n🔍 [RAG 검색 쿼리]: {query}")
    for i, d in enumerate(docs):
        print(f"   - 검색 결과 {i+1}: {d.page_content[:50]}...") # 앞부분 50자만 출력
    return json.dumps([{"content": d.page_content, "metadata": d.metadata} for d in docs], ensure_ascii=False)

# tool.py 내 route_tool 예시
@tool
def route_tool(payload: str):
    """출발지, 도착지 좌표와 이동 수단을 입력받아 상세 경로를 반환합니다."""
    try:
        p = json.loads(payload)
        # services.py의 4개 인자(start, end, mode, sub_mode)를 모두 전달
        return json.dumps(get_route(
            p.get("start"), 
            p.get("end"), 
            p.get("mode", "transit"), 
            p.get("sub_mode")
        ), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    
@tool
def lockers_tool(_query: str = ""):
    """서울 주요 지하철역 및 관광지의 물품 보관소 위치와 현황을 조회합니다."""
    return json.dumps(get_lockers(), ensure_ascii=False)

# 다른 파일에서 불러오기 쉽게 리스트로 묶어줍니다.
tools = [vector_search_tool, route_tool, lockers_tool]