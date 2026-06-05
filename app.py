import streamlit as st
import pandas as pd
import base64
import io
import re
from PIL import ImageGrab, Image
from openai import OpenAI

# 🔑 과장님의 OpenAI API 키
MY_OPENAI_KEY = st.secrets["OPENAI_API_KEY"] 
client = OpenAI(api_key=MY_OPENAI_KEY)

st.set_page_config(page_title="KR-GreenAgent (통합 연동)", page_icon="🏭", layout="wide")
st.sidebar.title("🏭 KR-GreenAgent")
st.sidebar.info("💡 1단계에서 추출된 사업장 목록이 2단계 드롭다운으로 자동 연동됩니다!")

# --- 세션 메모리 초기화 (1단계 데이터 기억용) ---
if "boundary_context" not in st.session_state:
    st.session_state["boundary_context"] = ""
# 💡 사업장 목록만 담아둘 리스트 메모리 추가
if "workplace_list" not in st.session_state:
    st.session_state["workplace_list"] = []

menu = ["🏢 1단계: 조직경계 AI 설정", "📂 2단계: 증빙자료 AI 판독"]
choice = st.sidebar.radio("업무 프로세스 선택:", menu)

def get_clipboard_image_base64():
    img = ImageGrab.grabclipboard()
    if img is None: return None
    try:
        if isinstance(img, list): img = Image.open(img[0])
        if img.mode != "RGB": img = img.convert("RGB")
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        st.error(f"이미지 변환 중 오류: {e}")
        return None

def reset_chat(step_name):
    st.session_state[f"messages_{step_name}"] = []
    st.session_state[f"image_context_{step_name}"] = None

def run_ai_vision(image_base64, system_instruction, prompt_text):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": [{"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}
        ],
        temperature=0.1
    )
    return response.choices[0].message.content

# ==========================================
# 🏢 1단계: 조직경계 AI 설정
# ==========================================
if choice == "🏢 1단계: 조직경계 AI 설정":
    st.title("🏢 1단계: 사업장 조직경계 AI 설정")
    if "messages_step1" not in st.session_state: st.session_state["messages_step1"] = []
    
    tab1, tab2 = st.tabs(["📂 파일 업로드", "✂️ 화면 캡처 (Ctrl+C)"])
    
    sys_prompt_1 = "당신은 한국선급(KR)의 온실가스 검증 심사원입니다. 통제적 접근 방식에 따라 조직경계를 설정하십시오."
    # 💡 AI에게 맨 마지막 줄에 사업장 이름만 쉼표로 나열하라고 강제 명령!
    init_prompt_1 = """
    사업자등록증 이미지 정보를 읽고 NGMS [명세서 2-1 사업장 일반정보], [명세서 2-2 사업장 조직경계 입력 및 코멘트] 양식에 맞추어 표를 그려줘.
    
    그리고 응답의 제일 마지막 줄에는 반드시 아래 형식으로만 분석된 사업장 이름들을 쉼표로 구분해서 적어줘. (예시: WORKPLACE_LIST: 본점, 울산지점, 부산공장)
    """

    def extract_workplace_list(ai_text):
        # AI 응답 텍스트에서 WORKPLACE_LIST: 부분만 쏙 빼서 리스트로 만드는 함수
        match = re.search(r"WORKPLACE_LIST:\s*(.+)", ai_text)
        if match:
            raw_list = match.group(1).split(",")
            return [x.strip() for x in raw_list if x.strip()]
        return []

    def process_image_step1(b64_image):
        reset_chat("step1")
        st.session_state["image_context_step1"] = b64_image
        with st.spinner("🤖 이미지를 판독하여 조직경계를 설정 중입니다..."):
            ai_msg = run_ai_vision(b64_image, sys_prompt_1, init_prompt_1)
            
            # 대화창에 출력할 때는 WORKPLACE_LIST 줄은 지워서 보여줌 (깔끔하게)
            display_msg = re.sub(r"WORKPLACE_LIST:\s*(.+)", "", ai_msg).strip()
            
            st.session_state["messages_step1"].append({"role": "assistant", "content": display_msg})
            st.session_state["boundary_context"] = display_msg
            
            # 💡 추출한 사업장 리스트를 메모리에 쏙 저장!
            workplaces = extract_workplace_list(ai_msg)
            if workplaces:
                st.session_state["workplace_list"] = workplaces
            else:
                # 못 찾으면 기본값이라도 넣어줌
                st.session_state["workplace_list"] = ["본점 (자동추출 실패)"]

    with tab1:
        uploaded_file = st.file_uploader("사업자등록증 파일 올리기", type=['jpg', 'jpeg', 'png'], key="up1")
        if uploaded_file and st.button("🚀 업로드 파일 분석", type="primary", key="btn1"):
            img = Image.open(uploaded_file).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            process_image_step1(base64.b64encode(buf.getvalue()).decode('utf-8'))
            
    with tab2:
        st.info("💡 윈도우 캡처(Shift+Win+S) 후 아래 버튼을 누르세요.")
        if st.button("📋 캡처본 분석", type="primary", key="btn2"):
            b64 = get_clipboard_image_base64()
            if b64: process_image_step1(b64)
            else: st.error("⚠️ 클립보드에 이미지가 없습니다!")

    st.divider()
    for msg in st.session_state["messages_step1"]:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if st.session_state.get("image_context_step1"):
        if user_input := st.chat_input("추가 지시 (예: 부산공장을 추가해 줘. 그리고 WORKPLACE_LIST: 본점, 부산공장 도 갱신해 줘)"):
            st.session_state["messages_step1"].append({"role": "user", "content": user_input})
            with st.chat_message("user"): st.markdown(user_input)
            with st.spinner("🤖 수정 중..."):
                api_messages = [{"role": "system", "content": sys_prompt_1}, {"role": "user", "content": [{"type": "text", "text": "이전 이미지야."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state['image_context_step1']}"}}]}]
                for m in st.session_state["messages_step1"]: api_messages.append({"role": m["role"], "content": m["content"]})
                
                reply = client.chat.completions.create(model="gpt-4o", messages=api_messages, temperature=0.1).choices[0].message.content
                
                # 티키타카 과정에서도 사업장 리스트가 갱신되면 업데이트
                new_workplaces = extract_workplace_list(reply)
                if new_workplaces: st.session_state["workplace_list"] = new_workplaces
                
                display_msg = re.sub(r"WORKPLACE_LIST:\s*(.+)", "", reply).strip()
                st.session_state["messages_step1"].append({"role": "assistant", "content": display_msg})
                st.session_state["boundary_context"] = display_msg
                with st.chat_message("assistant"): st.markdown(display_msg)

# ==========================================
# 📂 2단계: 증빙자료 판독 및 산정
# ==========================================
elif choice == "📂 2단계: 증빙자료 AI 판독":
    st.title("📂 2단계: 증빙서류 AI 사진(Vision) 판독")
    
    if st.session_state["boundary_context"]:
        st.success("🔗 1단계 조직경계 설정 완료!")
    else:
        st.warning("⚠️ 1단계 조직경계가 설정되지 않았습니다. (드롭다운에 기본값만 표시됩니다)")
        
    # 💡 1단계에서 추출된 리스트를 가져와서 드롭다운(selectbox)으로 띄움!
    options = st.session_state["workplace_list"] if st.session_state["workplace_list"] else ["본점", "지점 (직접입력)"]
    target_workplace = st.selectbox("📍 이 증빙서류를 배정할 사업장을 선택하세요:", options)

    if "messages_step2" not in st.session_state: st.session_state["messages_step2"] = []
    
    tab1, tab2 = st.tabs(["📂 파일 업로드", "✂️ 화면 캡처 (Ctrl+C)"])
    
    sys_prompt_2 = "당신은 한국선급(KR) 온실가스 검증 심사원입니다. '온실가스 명세서 검증 매뉴얼'에 근거하여 활동자료를 검증합니다."
    
    init_prompt_2 = f"""
    이 증빙자료는 '{target_workplace}' 사업장에서 발생한 자료야.
    이미지에서 수치를 추출하여 NGMS 양식에 맞추어 아래 표를 그려줘.
    
    ### 📝 [명세서 5] 배출활동별 배출량 현황
    | 사업장명 | Scope 분류 | 배출활동 (에너지원) | 적용 Tier | 연간 사용량 (추출값) | 적용 배출계수 | 산정 배출량 (tCO2eq) |
    |---|---|---|---|---|---|---|
    | {target_workplace} | (Scope 1/2) | (무연휘발유 등) | (예: Tier 1) | (수치 및 단위) | (계수) | (계산값) |
    
    표 아래에는 모니터링 유형 검토와 보수적계산 필요성 코멘트를 달아줘.
    """

    def process_image_step2(b64_image):
        reset_chat("step2")
        st.session_state["image_context_step2"] = b64_image
        with st.spinner(f"🤖 '{target_workplace}' 사업장으로 데이터를 맵핑하며 판독 중입니다..."):
            ai_msg = run_ai_vision(b64_image, sys_prompt_2, init_prompt_2)
            st.session_state["messages_step2"].append({"role": "assistant", "content": ai_msg})

    with tab1:
        uploaded_file = st.file_uploader("영수증/고지서 올리기", type=['jpg', 'jpeg', 'png'], key="up2")
        if uploaded_file and st.button("🚀 업로드 파일 초기 분석", type="primary", key="btn3"):
            img = Image.open(uploaded_file).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            process_image_step2(base64.b64encode(buf.getvalue()).decode('utf-8'))
            
    with tab2:
        st.info("💡 윈도우 캡처 후 아래 버튼을 누르세요.")
        if st.button("📋 캡처본 초기 분석", type="primary", key="btn4"):
            b64 = get_clipboard_image_base64()
            if b64: process_image_step2(b64)
            else: st.error("⚠️ 클립보드에 이미지가 없습니다!")

    st.divider()
    for msg in st.session_state["messages_step2"]:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if st.session_state.get("image_context_step2"):
        if user_input := st.chat_input("추가 정보 반영이나 수정을 지시하세요."):
            st.session_state["messages_step2"].append({"role": "user", "content": user_input})
            with st.chat_message("user"): st.markdown(user_input)
            with st.spinner("🤖 산정표를 수정 중입니다..."):
                api_messages = [{"role": "system", "content": sys_prompt_2}, {"role": "user", "content": [{"type": "text", "text": "이전 이미지야."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{st.session_state['image_context_step2']}"}}]}]
                for m in st.session_state["messages_step2"]: api_messages.append({"role": m["role"], "content": m["content"]})
                reply = client.chat.completions.create(model="gpt-4o", messages=api_messages, temperature=0.1).choices[0].message.content
                st.session_state["messages_step2"].append({"role": "assistant", "content": reply})
                with st.chat_message("assistant"): st.markdown(reply)
