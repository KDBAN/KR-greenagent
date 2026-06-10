import streamlit as st
import pandas as pd
import base64
import io
import re
import datetime
import json
import fitz  # PyMuPDF
from PIL import Image
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# 🔑 클라우드 연동 및 API 세팅
# ==========================================
MY_OPENAI_KEY = st.secrets["OPENAI_API_KEY"]
client = OpenAI(api_key=MY_OPENAI_KEY)

GOOGLE_SHEET_ID = "1gvj9ZcXsKBpMzy0JjbJeLaZoVrCQt_4ion0ODzgpwR8"
GOOGLE_DRIVE_FOLDER_ID = "1w-V62GNNKkk6UU3L2QtpXDqYJWhZdm9E"

def get_gcp_credentials():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    return Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)

def upload_image_to_drive(file_bytes, file_name, file_extension=".jpg"):
    if not file_bytes: return "수동 입력 (증빙 없음)"
    try:
        creds = get_gcp_credentials()
        drive_service = build('drive', 'v3', credentials=creds)
        drive_file_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}{file_extension}"
        file_metadata = {'name': drive_file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
        mime_type = 'application/pdf' if file_extension.lower() == '.pdf' else 'image/jpeg'
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        return file.get('webViewLink')
    except Exception as e: return f"업로드 실패: {e}"

def save_to_google_sheets(data_dict):
    try:
        creds = get_gcp_credentials()
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
        row_data = [
            data_dict.get("등록일시", ""), data_dict.get("사업장명", ""), data_dict.get("조직(부서/공정)", ""), 
            data_dict.get("배출시설코드", ""), data_dict.get("배출시설명", ""), data_dict.get("자체시설명", ""),
            data_dict.get("Scope", ""), data_dict.get("배출활동", ""), data_dict.get("사용량", ""), 
            data_dict.get("단위", ""), data_dict.get("배출계수(CO2)", ""), data_dict.get("총배출량(tCO2eq)", ""), 
            data_dict.get("증빙 원본 링크", "")
        ]
        sheet.append_row(row_data)
        return True
    except Exception as e: return False

# ==========================================
# 🔐 시스템 메모리 & 초기화
# ==========================================
st.set_page_config(page_title="KR-GreenAgent Master Builder", page_icon="🏭", layout="wide")

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_id" not in st.session_state: st.session_state["user_id"] = ""

if not st.session_state["logged_in"]:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 KR-GreenAgent")
        st.caption("NGMS 명세서 수동/자동 통합 빌더 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

# 💡 [핵심] 리스트들을 딕셔너리로 단단하게 구조화
if "workplace_list" not in st.session_state: st.session_state["workplace_list"] = []
if "facility_list" not in st.session_state: st.session_state["facility_list"] = []
if "inventory_db" not in st.session_state: st.session_state["inventory_db"] = [] 

if "msg_step1" not in st.session_state: st.session_state["msg_step1"] = []
if "msg_step2" not in st.session_state: st.session_state["msg_step2"] = []
if "msg_step3" not in st.session_state: st.session_state["msg_step3"] = []

if "current_file_bytes" not in st.session_state: st.session_state["current_file_bytes"] = None
if "current_file_ext" not in st.session_state: st.session_state["current_file_ext"] = ".jpg"

st.sidebar.title("🏭 KR-GreenAgent")
st.sidebar.success(f"👤 **{st.session_state['user_id']}** 검증원 접속 중")
if st.sidebar.button("로그아웃/초기화"):
    st.session_state.clear()
    st.rerun()

st.title("🏭 KR-GreenAgent : 하이브리드 명세서 빌더")
st.markdown("이미지(AI 판독)와 **수동 타이핑 입력**을 모두 지원하는 완벽한 명세서 구축 시스템입니다.")

def convert_multiple_files_to_image_bytes(uploaded_files):
    all_image_bytes = []
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    try:
        for file in uploaded_files:
            if file.name.lower().endswith('.pdf'):
                pdf_document = fitz.open(stream=file.read(), filetype="pdf")
                for page_num in range(min(len(pdf_document), 10)):
                    page = pdf_document.load_page(page_num)
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=95)
                    all_image_bytes.append(base64.b64encode(buf.getvalue()).decode('utf-8'))
            else:
                img = Image.open(file).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                all_image_bytes.append(base64.b64encode(buf.getvalue()).decode('utf-8'))
        return all_image_bytes
    except: return []

def get_clipboard_image_bytes_list():
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is None: return []
        if isinstance(img, list): img = Image.open(img[0])
        if img.mode != "RGB": img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return [base64.b64encode(buf.getvalue()).decode('utf-8')]
    except: return []

def run_ai_vision_multi(image_base64_list, system_instruction, prompt_text):
    content_list = [{"type": "text", "text": prompt_text}]
    for b64_img in image_base64_list:
        content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}})
    response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": content_list}], temperature=0.0)
    return response.choices[0].message.content

# 💡 문자열에서 딕셔너리로 추출하도록 변경
def extract_workplace_dicts(ai_text):
    match = re.search(r"WORKPLACE_LIST:\s*(.+)", ai_text)
    result = []
    if match:
        raw_list = match.group(1).split(",")
        for x in raw_list:
            m = re.match(r"\[(.*?)\]\s*(.*)", x.strip())
            if m:
                result.append({"사업장명": m.group(1).strip(), "하위조직": m.group(2).strip()})
    return result

def extract_json_from_text(ai_text):
    try:
        match = re.search(r"```json\n(.*?)\n```", ai_text, re.DOTALL)
        if match: return json.loads(match.group(1))
        return None
    except: return None

# ==========================================
# 🏢 1단계: 조직경계 (사업장/하위부서)
# ==========================================
with st.expander("🏢 1단계: 사업장 및 하위 조직(부서/공정) 등록", expanded=True if not st.session_state["workplace_list"] else False):
    
    # 💡 3개의 탭으로 분리 (파일 / 캡처 / 수동입력)
    t1_1, t1_2, t1_3 = st.tabs(["📂 AI 문서 업로드", "✂️ AI 화면 캡처", "✍️ 수동 직접 입력"])
    
    sys_prompt_1 = "[SYSTEM COMMAND] 당신은 KR 명세서 빌더 AI입니다. 문서를 읽고 지시를 수행하십시오."
    init_prompt_1 = """
    문서를 분석하여 명세서 1-2(사업장 목록) 및 2-1(사업장 일반정보)을 위한 계층 구조를 파악해 줘.
    [매우 중요]
    응답의 제일 마지막 줄에는 반드시 아래 형식으로만 '사업장명 - 소속본부/팀'을 묶어서 쉼표로 구분해 적어줘!
    형식 예시: WORKPLACE_LIST: [본사] 경영지원팀, [울산공장] 1생산팀, [울산공장] 폐수처리장
    """

    def process_step1(b64_list):
        st.session_state["msg_step1"] = []
        with st.spinner("🤖 문서를 분석하여 계층구조를 생성 중입니다..."):
            ai_msg = run_ai_vision_multi(b64_list, sys_prompt_1, init_prompt_1)
            workplaces = extract_workplace_dicts(ai_msg)
            if workplaces:
                for wp in workplaces:
                    if wp not in st.session_state["workplace_list"]:
                        st.session_state["workplace_list"].append(wp)
            
            display_msg = re.sub(r"WORKPLACE_LIST:\s*(.+)", "", ai_msg).strip()
            st.session_state["msg_step1"].append({"role": "assistant", "content": display_msg})
            st.rerun()

    with t1_1:
        col1, col2 = st.columns([3, 1])
        with col1: up1 = st.file_uploader("📂 사업자등록증/조직도 (다중 지원)", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u1")
        with col2:
            st.markdown("<br><br>", unsafe_allow_html=True)
            if st.button("🚀 1단계 AI 조직도 분석", type="primary", use_container_width=True):
                b64_list = convert_multiple_files_to_image_bytes(up1) if up1 else None
                if b64_list: process_step1(b64_list)

    with t1_2:
        st.info("💡 윈도우 캡처(`Shift+Win+S`) 후 아래 버튼을 누르세요.")
        if st.button("📋 캡처본 AI 분석", type="primary"):
            b64_list = get_clipboard_image_bytes_list()
            if b64_list: process_step1(b64_list)
            else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
            
    with t1_3:
        # 💡 [핵심] 완전 수동 입력 폼
        with st.form("manual_org_form"):
            st.write("문서 없이 키보드로 직접 조직을 생성합니다.")
            col_m1, col_m2 = st.columns(2)
            m_wp_name = col_m1.text_input("사업장명 (예: 부산본사, 울산공장)")
            m_dept_name = col_m2.text_input("하위 부서/공정 (예: 영업본부, 1생산팀)")
            if st.form_submit_button("✍️ 조직경계 수동 추가", type="primary"):
                if m_wp_name and m_dept_name:
                    new_org = {"사업장명": m_wp_name.strip(), "하위조직": m_dept_name.strip()}
                    if new_org not in st.session_state["workplace_list"]:
                        st.session_state["workplace_list"].append(new_org)
                        st.success(f"✅ [{new_org['사업장명']}] {new_org['하위조직']} 등록 완료!")
                        st.rerun()
                else: st.error("빈칸을 모두 채워주세요.")

    # 등록된 조직 리스트 보여주기
    if st.session_state["workplace_list"]:
        st.markdown("#### 📌 현재 등록된 조직경계 목록")
        st.dataframe(pd.DataFrame(st.session_state["workplace_list"]), use_container_width=True)

# ==========================================
# ⚙️ 2단계: 배출시설 정의 (명세서 3-1)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("⚙️ 2단계: 조직별 배출시설 정의 (명세서 3-1)", expanded=True if st.session_state["workplace_list"] and not st.session_state["facility_list"] else False):
    
    if not st.session_state["workplace_list"]: st.warning("⚠️ 1단계 조직경계를 먼저 등록해주세요.")
    else:
        # 드롭다운용 인덱스 생성
        org_options = {i: f"[{wp['사업장명']}] {wp['하위조직']}" for i, wp in enumerate(st.session_state["workplace_list"])}
        target_org_idx = st.selectbox("📍 배출시설을 등록할 조직을 선택하세요:", options=list(org_options.keys()), format_func=lambda x: org_options[x])
        selected_org = st.session_state["workplace_list"][target_org_idx]
        
        t2_1, t2_2, t2_3 = st.tabs(["📂 AI 도면 업로드", "✂️ AI 화면 캡처", "✍️ 수동 직접 입력"])
        
        sys_prompt_2 = "[SYSTEM COMMAND] 배출시설 맵핑 AI입니다."
        init_prompt_2 = f"""
        이 도면/자료는 '{org_options[target_org_idx]}' 소속이야.
        파악되는 배출시설을 추출해서 JSON 배열로 줘.
        [JSON 예시]
        ```json
        [
          {{"배출시설코드": "0055", "배출시설명": "일반 보일러시설", "자체시설명": "온수보일러 1호기", "주요에너지원": "LNG"}},
          {{"배출시설코드": "0098", "배출시설명": "사업장단위 전력사용시설", "자체시설명": "메인수전반", "주요에너지원": "전력"}}
        ]
        ```
        """

        def process_step2(b64_list):
            st.session_state["msg_step2"] = []
            with st.spinner(f"🤖 도면을 분석 중입니다..."):
                ai_msg = run_ai_vision_multi(b64_list, sys_prompt_2, init_prompt_2)
                json_data = extract_json_from_text(ai_msg)
                if json_data:
                    for f in json_data:
                        # 상위 조직 정보 합치기
                        f["사업장명"] = selected_org["사업장명"]
                        f["하위조직"] = selected_org["하위조직"]
                        st.session_state["facility_list"].append(f)
                    st.rerun()

        with t2_1:
            col3, col4 = st.columns([3, 1])
            with col3: up2 = st.file_uploader("📂 시설도면 / 설비대장 (다중 지원)", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u2")
            with col4:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button("🚀 2단계 배출시설 AI 추출", type="primary", use_container_width=True):
                    b64_list = convert_multiple_files_to_image_bytes(up2) if up2 else None
                    if b64_list: process_step2(b64_list)
                    
        with t2_2:
            st.info("💡 윈도우 캡처 후 아래 버튼을 누르세요.")
            if st.button("📋 캡처본 배출시설 AI 추출", type="primary", key="btn_c2"):
                b64_list = get_clipboard_image_bytes_list()
                if b64_list: process_step2(b64_list)
                else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
                
        with t2_3:
            # 💡 [핵심] 완전 수동 배출시설 등록
            with st.form("manual_facility"):
                st.write("도면 없이 키보드로 배출시설을 직접 등록합니다.")
                col_f1, col_f2, col_f3 = st.columns(3)
                f_code = col_f1.text_input("배출시설코드 (예: 0055)")
                f_name = col_f2.text_input("배출시설명 (예: 일반 보일러시설)")
                f_subname = col_f3.text_input("자체시설명 (예: 온수보일러)")
                if st.form_submit_button("✍️ 배출시설 수동 추가", type="primary"):
                    if f_code and f_name:
                        st.session_state["facility_list"].append({
                            "사업장명": selected_org["사업장명"], "하위조직": selected_org["하위조직"],
                            "배출시설코드": f_code.strip(), "배출시설명": f_name.strip(), "자체시설명": f_subname.strip(), "주요에너지원": "수동입력"
                        })
                        st.success(f"✅ {f_subname} 시설 등록 완료!")
                        st.rerun()
                    else: st.error("필수 항목(코드, 시설명)을 입력하세요.")

        if st.session_state["facility_list"]:
            st.markdown("#### 📌 현재 등록된 배출시설 목록")
            st.dataframe(pd.DataFrame(st.session_state["facility_list"]), use_container_width=True)

# ==========================================
# 📂 3단계: 활동자료(증빙) 판독 및 산정 (명세서 5)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📂 3단계: 활동자료(증빙/전표) 입력 및 배출량 산정 (명세서 5)", expanded=True):
    
    if not st.session_state["facility_list"]: st.warning("⚠️ 2단계에서 배출시설을 먼저 등록하세요.")
    else:
        fac_options = {i: f"[{f['사업장명']}] {f['하위조직']} - {f['배출시설코드']}_{f['배출시설명']}({f['자체시설명']})" for i, f in enumerate(st.session_state["facility_list"])}
        target_fac_idx = st.selectbox("📍 전표를 귀속시킬 배출시설을 선택하세요:", options=list(fac_options.keys()), format_func=lambda x: fac_options[x])
        selected_fac = st.session_state["facility_list"][target_fac_idx]

        t3_1, t3_2, t3_3 = st.tabs(["📂 AI 영수증 업로드", "✂️ AI 화면 캡처", "✍️ 수동 전표 직접 입력"])
        
        sys_prompt_3 = "[SYSTEM COMMAND] KR 온실가스 검증 심사원입니다. 증빙자료의 수치를 추출해 계산하십시오."
        init_prompt_3 = f"""
        이 증빙자료는 '{fac_options[target_fac_idx]}' 에 속한 자료야.
        문서 수치를 읽고 [명세서 5] 양식에 맞춰 아래 JSON을 작성해.
        ```json
        {{ 
          "Scope": "Scope 1 또는 2", 
          "배출활동": "무연휘발유, 전력, LNG 등", 
          "사용량": 1488.75, 
          "단위": "L, kWh 등", 
          "배출계수(CO2)": 2.7657, 
          "총배출량(tCO2eq)": 4.11
        }}
        ```
        """

        def process_step3(up_files, b64_list):
            st.session_state["msg_step3"] = []
            try:
                if up_files:
                    st.session_state["current_file_bytes"] = (up_files[0] if isinstance(up_files, list) else up_files).getvalue()
                    st.session_state["current_file_ext"] = ".pdf" if (up_files[0] if isinstance(up_files, list) else up_files).name.lower().endswith('.pdf') else ".jpg"
                else:
                    st.session_state["current_file_bytes"] = base64.b64decode(b64_list[0])
                    st.session_state["current_file_ext"] = ".jpg"
                    
                with st.spinner("🤖 영수증 판독 중..."):
                    ai_msg = run_ai_vision_multi(b64_list, sys_prompt_3, init_prompt_3)
                    json_data = extract_json_from_text(ai_msg)
                    if json_data:
                        # 시설 정보 병합
                        json_data.update(selected_fac)
                        
                        drive_link = upload_image_to_drive(st.session_state["current_file_bytes"], "활동자료", st.session_state["current_file_ext"])
                        json_data["등록일시"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        json_data["담당 검증원"] = st.session_state["user_id"]
                        json_data["증빙 원본 링크"] = drive_link
                        
                        save_to_google_sheets(json_data)
                        st.session_state["inventory_db"].append(json_data)
                        st.success("🎉 AI 자동판독 및 DB 저장 완료!")
                        st.rerun()
            except Exception as e: st.error(f"오류: {e}")

        with t3_1:
            col5, col6 = st.columns([3, 1])
            with col5: up3 = st.file_uploader("📂 영수증/고지서 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u3")
            with col6:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button("🚀 3단계 활동자료 AI 분석", type="primary", use_container_width=True):
                    b64_list = convert_multiple_files_to_image_bytes(up3) if up3 else None
                    if b64_list: process_step3(up3, b64_list)

        with t3_2:
            st.info("💡 윈도우 캡처(Shift+Win+S) 후 아래 버튼을 누르세요.")
            if st.button("📋 캡처본 전표 AI 분석", type="primary", key="btn_c3"):
                b64_list = get_clipboard_image_bytes_list()
                if b64_list: process_step3(None, b64_list)
                else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
                
        with t3_3:
            # 💡 [핵심] 완전 수동 전표(데이터) 입력 폼! 영수증 없이도 입력 가능!
            with st.form("manual_activity"):
                st.write("📝 증빙이 없거나 수동으로 입력할 데이터를 작성합니다.")
                c_a1, c_a2, c_a3 = st.columns(3)
                m_scope = c_a1.selectbox("Scope 분류", ["Scope 1", "Scope 2", "Scope 3"])
                m_activity = c_a2.text_input("배출활동 (예: 전력, LNG)")
                m_usage = c_a3.number_input("사용량", min_value=0.0, format="%.2f")
                
                c_a4, c_a5, c_a6 = st.columns(3)
                m_unit = c_a4.text_input("단위 (예: kWh, L, Nm3)")
                m_factor = c_a5.number_input("배출계수", min_value=0.0, format="%.4f")
                m_emission = c_a6.number_input("총 산정 배출량(tCO2eq)", min_value=0.0, format="%.2f")
                
                if st.form_submit_button("✍️ 수동 전표 DB 확정 등록", type="primary"):
                    if m_activity:
                        manual_data = {
                            "등록일시": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "담당 검증원": st.session_state["user_id"],
                            "Scope": m_scope, "배출활동": m_activity, "사용량": m_usage, "단위": m_unit, 
                            "배출계수(CO2)": m_factor, "총배출량(tCO2eq)": m_emission, "증빙 원본 링크": "수동 입력 (증빙 없음)"
                        }
                        manual_data.update(selected_fac) # 선택된 시설 정보 병합
                        save_to_google_sheets(manual_data)
                        st.session_state["inventory_db"].append(manual_data)
                        st.success("🎉 수동 전표가 DB에 완벽하게 저장되었습니다!")
                        st.rerun()
                    else: st.error("필수 항목을 입력하세요.")

# ==========================================
# 🗄️ 4단계: NGMS 명세서 출력 (DB 연동)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📄 4단계: [최종] 온실가스 명세서 종합 리포트 생성", expanded=True):
    st.title("📄 온실가스 배출량 및 에너지 사용량 명세서")
    
    if len(st.session_state["inventory_db"]) == 0:
        st.info("아직 3단계에서 확정 저장된 배출량 전표가 없습니다.")
    else:
        st.success("✅ 명세서 초안이 작성되었습니다. 제출용 문서 형식(HTML)으로 제공됩니다.")
        
        df = pd.DataFrame(st.session_state["inventory_db"])
        total_co2 = pd.to_numeric(df["총배출량(tCO2eq)"], errors='coerce').sum()
        
        report_html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Malgun Gothic', sans-serif; padding: 20px; }}
                h1, h2 {{ text-align: center; color: #2C3E50; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 12px; }}
                th, td {{ border: 1px solid #34495E; padding: 8px; text-align: center; }}
                th {{ background-color: #ECF0F1; font-weight: bold; }}
                .summary-box {{ border: 2px solid #2C3E50; padding: 15px; margin: 20px 0; background-color: #F8F9F9; }}
                .footer {{ text-align: right; margin-top: 50px; font-size: 14px; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h1>온실가스 배출량 및 에너지 사용량 명세서</h1>
            <p style="text-align:center;">「기후위기 대응을 위한 탄소중립·녹색성장 기본법」 제27조제3항에 따라 아래와 같이 보고합니다.</p>
            
            <div class="summary-box">
                <h3>1. 할당대상업체(관리업체) 총괄 정보</h3>
                <p><b>■ 제출 일자 :</b> {datetime.datetime.now().strftime("%Y년 %m월 %d일")}</p>
                <p><b>■ 담당 검증원 :</b> {st.session_state["user_id"]}</p>
                <p><b>■ 산정된 총 온실가스 배출량 :</b> <span style="color:red; font-size:18px;"><b>{total_co2:,.2f} tCO2-eq</b></span></p>
            </div>

            <h2>5. 배출활동별 배출량 현황 (세부 명세)</h2>
            <table>
                <thead>
                    <tr>
                        <th>연번</th>
                        <th>사업장명</th>
                        <th>하위조직(공정)</th>
                        <th>배출시설코드</th>
                        <th>배출시설명(자체명)</th>
                        <th>Scope</th>
                        <th>배출활동(연료)</th>
                        <th>사용량</th>
                        <th>단위</th>
                        <th>배출계수</th>
                        <th>배출량(tCO2eq)</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for i, row in df.iterrows():
            report_html += f"""
                    <tr>
                        <td>{i+1}</td>
                        <td>{row.get('사업장명','')}</td>
                        <td>{row.get('조직(부서/공정)','')}</td>
                        <td>{row.get('배출시설코드','')}</td>
                        <td>{row.get('배출시설명','')} ({row.get('자체시설명','')})</td>
                        <td>{row.get('Scope','')}</td>
                        <td>{row.get('배출활동','')}</td>
                        <td>{row.get('사용량','')}</td>
                        <td>{row.get('단위','')}</td>
                        <td>{row.get('배출계수(CO2)','')}</td>
                        <td><b>{row.get('총배출량(tCO2eq)','')}</b></td>
                    </tr>
            """
            
        report_html += """
                </tbody>
            </table>
        </body>
        </html>
        """

        st.components.v1.html(report_html, height=600, scrolling=True)
        
        b64_html = base64.b64encode(report_html.encode('utf-8')).decode('utf-8')
        href = f'<br><a href="data:text/html;base64,{b64_html}" download="KR_GHG_Report_{datetime.datetime.now().strftime("%Y%m%d")}.html" style="text-decoration:none; padding:10px 20px; background-color:#2C3E50; color:white; border-radius:5px; font-weight:bold;">📥 명세서 종합 리포트 다운로드 (HTML 문서)</a>'
        st.markdown(href, unsafe_allow_html=True)
