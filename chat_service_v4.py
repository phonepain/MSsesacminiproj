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
mini_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=OPENAI_API_KEY).bind_tools(tools)
pro_llm = ChatOpenAI(model="gpt-4o", temperature=0, api_key=OPENAI_API_KEY).with_structured_output(FinalResponse)

# --- 3. 노드 구현 ---

def researcher_node(state: AgentState):
    """[Researcher] 400 에러와 무한 루프를 방지하는 스마트 슬라이싱 적용"""
    all_messages = state["messages"]
    
    # [핵심] 400 에러 방지: 마지막 HumanMessage 이후의 모든 메시지를 가져와 도구 쌍을 유지합니다.
    # 이렇게 하면 slicing으로 인해 tool_calls가 잘려나가는 것을 막을 수 있습니다.
    last_human_idx = -1
    for i in range(len(all_messages)-1, -1, -1):
        if isinstance(all_messages[i], HumanMessage):
            last_human_idx = i
            break
    
    # 마지막 질문부터 현재까지의 흐름을 모두 전달 (도구 결과 포함 -> 무한 루프 방지)
    input_messages = all_messages[last_human_idx:] if last_human_idx != -1 else all_messages[-5:]
    
    system_msg = SystemMessage(content="You are a travel search assistant. Use tools to find specific info.")
    response = mini_llm.invoke([system_msg] + input_messages)
    return {"messages": [response]}

def formatter_node(state: AgentState):
    """[Formatter] 데이터 규격(Format)을 강제하고 사이드바 업데이트를 유도합니다."""
    # trip_context가 리스트이므로 기본값을 []로 설정
    context_str = json.dumps(state.get("trip_context", []), ensure_ascii=False)
    
    prompt = f"""
    {SYSTEM_INSTRUCTION}
    
    [현재 사이드바 일정 상태]
    {context_str}
    
    지침: 위 상태를 바탕으로 'planUpdates' 배열을 채우세요. 
    사용자에게는 'response'로 짧게 답하고, 모든 데이터는 'planUpdates'에 넣어야 사이드바에 표시됩니다.
    """
    
    # 포맷터는 깨끗한 대화만 필요하므로 도구 메시지 제외 (400 에러 방지)
    safe_messages = [m for m in state["messages"] if isinstance(m, (HumanMessage, AIMessage)) and not getattr(m, 'tool_calls', None)]
    
    response = pro_llm.invoke([SystemMessage(content=prompt)] + safe_messages[-3:])
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
    return {
        'success': True, 
        'response': final_result.get('response', ''), 
        'planUpdates': final_result.get('planUpdates', [])
    }