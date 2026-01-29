import json
import operator
from typing import Annotated, List, Optional, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from config import OPENAI_API_KEY, SYSTEM_INSTRUCTION
from tool import tools
from schema import FinalResponse

# --- 1. 상태 정의 ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    trip_context: list # 리스트 형식이므로 list로 명시
    final_json: Optional[dict]
    retry_count: int

# --- 2. 모델 설정 ---
mini_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=OPENAI_API_KEY).bind_tools(tools)
pro_llm = ChatOpenAI(model="gpt-4o", temperature=0.3, api_key=OPENAI_API_KEY).with_structured_output(FinalResponse)

# --- 3. 노드 구현 ---

# chat_service_v4.py 최종 수정본

def researcher_node(state: AgentState):

    """[Researcher] 모든 날짜의 일정에 필요한 도구를 다 사용했는지 검토합니다."""
    all_messages = state["messages"]
    
    context = state.get("trip_context", [])
    context_brief = ""
    if context:
        context_brief = f"\n[현재 확정된 일정 요약]: {json.dumps(context, ensure_ascii=False)[:1000]}"
    
    # [핵심] 400 에러 방지 로직: 
    # 도구 결과(ToolMessage)가 있다면 반드시 그 앞의 도구 호출(AIMessage)도 포함해야 합니다.
    # 테스트 및 검색 효율을 위해, '현재 질문'과 관련된 맥락만 필터링하여 전달합니다.
    safe_messages = []
    for msg in all_messages:
        if isinstance(msg, HumanMessage):
            safe_messages.append(msg)
        elif isinstance(msg, AIMessage):
            # 도구 호출이 없는 일반 응답만 포함하거나, 
            # 도구 호출이 있다면 이후에 ToolMessage가 따라올 것이므로 일단 제외하고
            # 마지막 질문(HumanMessage) 이후의 흐름만 타이트하게 잡습니다.
            if not msg.tool_calls:
                safe_messages.append(msg)

    # 마지막 질문 이후의 메시지만 추출하여 도구 호출 쌍이 깨질 확률을 원천 차단
    last_human_idx = -1
    for i in range(len(all_messages)-1, -1, -1):
        if isinstance(all_messages[i], HumanMessage):
            last_human_idx = i
            break
    
    input_messages = all_messages[last_human_idx:] if last_human_idx != -1 else safe_messages[-5:]
    
    system_msg = SystemMessage(content="""당신은 여행 계획 검색 전문가입니다.
    {context_brief}
    사용자가 요청한 전체 기간(예: 3일치)에 대해 다음을 수행하세요:
    1. 모든 방문지의 좌표(lat, lng)를 검색했는가?

    아직 정보가 부족한 날짜가 있다면 해당 도구를 계속 호출하세요.
    단, 특정 정보가 계속 나오지 않는다면 억지로 찾지 말고 다음 단계로 넘어가세요.
    서울의 전통시장, 맛집 골목 정보 category:traditional_market
    서울 및 수도권 지하철역의 위치 정보 category:subway_station
    서울의 박물관, 미술관, 테마 거리, 관광 명소 정보를 검색합니다. category:museum_art, category:tourism_street

    모든 날짜의 경로 데이터가 수집될 때까지 포맷터로 넘어가지 마세요.
                               """)
    search_count = state.get("search_count", 0)
    print(f"\n🤖 [Researcher Node] 탐색 차수: {search_count + 1}")

    response = mini_llm.invoke([system_msg] + input_messages)

    if response.tool_calls:
        for tool in response.tool_calls:
            print(f"   🛠️ 호출 도구: {tool['name']}")
    else:
        print("   ✅ 도구 호출 없이 포맷터로 이동 준비 완료")

    return {"messages": [response]}

def formatter_node(state: AgentState):
    """[Formatter] trip_context를 안전하게 전달하고 최종 JSON 생성"""
    # trip_context가 리스트이므로 안전하게 처리
    context = state.get("trip_context", [])
    context_str = json.dumps(context, ensure_ascii=False)
    
    tool_contents = [m.content for m in state["messages"] if isinstance(m, ToolMessage)]
    tool_context_str = "\n".join(tool_contents)

    # 토큰 에러(429) 방지를 위한 컨텍스트 요약
    if len(context_str) > 2000:
        context_str = context_str[:2000] + "...(중략)"

    prompt = f"""
    {SYSTEM_INSTRUCTION}
    
    [중요: 수집된 도구 데이터]
    다음은 researcher가 도구를 통해 수집한 실제 경로 및 장소 정보입니다. 
    이 데이터를 바탕으로 'transport'와 'lat/lng'을 채우세요:
    {tool_context_str}
    
    [현재 여행 일정 상태]
    {json.dumps(context, ensure_ascii=False)}

    [지시]
    위 데이터를 바탕으로 사용자의 요청에 맞는 일정을 구성하되, 
    'planUpdates'의 각 원소는 반드시 하나의 날짜(day) 정보만 담아야 합니다. 
    1일차 활동들은 day: 1인 객체에, 2일차 활동들은 day: 2인 객체에 나누어 담으세요.    
    주의: 사용자가 가고 싶어 하는 장소의 이름(location), 좌표(lat, lng), 활동 요약(description)을 
    반드시 'planUpdates' 배열에 담아 사이드바를 업데이트하세요.
    """
    
    # 포맷터는 도구 호출 과정이 필요 없으므로 깨끗한 메시지만 전달 (400 에러 방지)
    clean_messages = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage)) and not getattr(m, 'tool_calls', None)]
    
    response = pro_llm.invoke([SystemMessage(content=prompt)] + clean_messages[-3:])

    # response = pro_llm.invoke([SystemMessage(content=prompt)] + state["messages"][-3:])
    final_data = response.dict()

    print("\n📦 [Final Formatter Output]")
    for up in final_data.get("planUpdates", []):
        day = up.get("day")
        # activities 중 transport 필드가 JSON 형태인지 체크
        acts = up.get("activities", [])
        has_route = any("{" in str(a.get("transport", "")) for a in acts)
        print(f"   📅 {day}일차 일정: {'✅ 경로 포함' if has_route else '❌ 경로 누락'}")
    return {"final_json": response.dict(), "retry_count": state.get("retry_count", 0) + 1}

# --- 4. 검증 및 그래프 구축 ---

def validate_output(state: AgentState):
    output = state.get("final_json", {})
    updates = output.get("planUpdates", [])
    for up in updates:
        act = up.get("activity") or (up.get("activities")[0] if up.get("activities") else None)
        if act and (act.get("lat") == 0 or act.get("lng") == 0) and state["retry_count"] < 3:
            return "formatter"
    return END

workflow = StateGraph(AgentState)
workflow.add_node("researcher", researcher_node)
workflow.add_node("tools", ToolNode(tools))
workflow.add_node("formatter", formatter_node)

workflow.set_entry_point("researcher")
workflow.add_conditional_edges("researcher", lambda x: "tools" if x["messages"][-1].tool_calls else "formatter")
workflow.add_edge("tools", "researcher")
workflow.add_conditional_edges("formatter", validate_output)

app = workflow.compile(checkpointer=MemorySaver())

# --- 5. 외부 인터페이스 ---

def handle_chat(user_message, trip_context, lang='ko'):
    config = {"configurable": {"thread_id": "web_session_v4"}}
    initial_state = {
        "messages": [HumanMessage(content=f"Language: {lang}\nMessage: {user_message}")],
        "trip_context": trip_context,
        "retry_count": 0
    }
    
    final_result = None
    try:
        for output in app.stream(initial_state, config=config):
            for node_name, state in output.items():
                if "final_json" in state:
                    final_result = state["final_json"]
    except Exception as e:
        print(f"Graph Error: {e}")
        return {'success': False, 'response': "에러가 발생했습니다.", 'planUpdates': []}

    if not final_result:
        return {'success': False, 'response': "응답을 생성하지 못했습니다.", 'planUpdates': []}

    # index.html이 기대하는 success, response, planUpdates 필드를 정확히 반환
    print(f"--- [DEBUG] AI Final Response ---")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))

    return {
        'success': True, 
        'response': final_result.get('response', ''), 
        'planUpdates': final_result.get('planUpdates', [])
    }
