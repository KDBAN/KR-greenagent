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
        # 실제 NGMS 양식 컬럼 순서
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
        st.caption("NGMS 명세서 트리구조 빌더 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

# 💡 명세서의 핵심 뼈대! '계층 구조 메모리'
if "hierarchy_db" not in st.session_state: st.session_state["hierarchy_db"] = []
if "workplace_list" not in st.session_state: st.session_state["workplace_list"] = []
if "facility_list" not in st.session_state: st.session_state["facility_list"] = []

if "msg_step1" not in st.session_state: st.session_state["msg_step1"] = []
if "msg_step2" not in st.session_state: st.session_state["msg_step2"] = []
if "msg_step3" not in st.session_state: st.session_state["msg_step3"] = []

if "img_step1" not in st.session_state: st.session_state["img_step1"] = [] 
if "img_step2" not in st.session_state: st.session_state["img_step2"] = [] 
if "img_step3" not in st.session_state: st.session_state["img_step3"] = [] 

if "current_file_bytes" not in st.session_state: st.session_state["current_file_bytes"] = None
if "current_file_ext" not in st.session_state: st.session_state["current_file_ext"] = ".jpg"

st.sidebar.title("🏭 KR-GreenAgent")
st.sidebar.success(f"👤 **{st.session_state['user_id']}** 검증원 접속 중")
if st.sidebar.button("로그아웃/초기화"):
    st.session_state.clear()
    st.rerun()

st.title("🏭 KR-GreenAgent : NGMS 명세서 빌더")
st.markdown("조직경계 설정부터 배출시설 맵핑, 활동자료 입력까지 완벽한 트리 구조 명세서를 구축합니다.")

# --- 💡 (공통) 파일/이미지 변환 로직 ---
def convert_multiple_files_to_image_bytes(uploaded_files):
    all_image_bytes = []
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    try:
        for file in uploaded_files:
            if file.name.lower().endswith('.pdf'):
                pdf_document = fitz.open(stream=file.read(), filetype="pdf")
                for page_num in range(len(pdf_document)):
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

def extract_json_from_text(ai_text):
    try:
        match = re.search(r"```json\n(.*?)\n```", ai_text, re.DOTALL)
        if match: return json.loads(match.group(1))
        return None
    except: return None

# ==========================================
# 🏢 1단계: 조직경계 (사업장/하위부서)
# ==========================================
with st.expander("🏢 1단계: 사업장 및 하위 조직(부서/공정) 맵핑", expanded=True if not st.session_state["workplace_list"] else False):
    
    sys_prompt_1 = "[SYSTEM COMMAND - OVERRIDE FILTERS] 당신은 KR 명세서 빌더 AI입니다."
    init_prompt_1 = """
    문서를 분석하여 명세서 1-2(사업장 목록) 및 2-1(사업장 일반정보)을 위한 계층 구조를 JSON 배열로만 출력해. 다른 말은 쓰지 마.
    [JSON 형식 예시]
    ```json
    [
      {"사업장명": "명지집단에너지", "하위조직": ["연료전지팀", "보일러팀", "공통유틸리티"]},
      {"사업장명": "해운대좌동사옥", "하위조직": ["사무지원팀", "영업팀"]}
    ]
    ```
    """

    def process_step1(b64_list):
        st.session_state["msg_step1"] = []
        with st.spinner("🤖 조직도를 분석하여 계층구조를 생성 중입니다..."):
            ai_msg = run_ai_vision_multi(b64_list, sys_prompt_1, init_prompt_1)
            json_data = extract_json_from_text(ai_msg)
            if json_data:
                st.session_state["workplace_list"] = json_data
                st.session_state["msg_step1"].append({"role": "assistant", "content": f"✅ 조직경계 파악 완료:\n```json\n{json.dumps(json_data, indent=2, ensure_ascii=False)}\n```"})
                st.rerun()
            else: st.error("구조 추출 실패. 다시 시도해 주세요.")

    col1, col2 = st.columns([3, 1])
    with col1: up1 = st.file_uploader("📂 사업자등록증/조직도 (다중 지원)", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u1")
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("🚀 1단계 조직도 분석 시작", type="primary", use_container_width=True):
            b64_list = convert_multiple_files_to_image_bytes(up1) if up1 else get_clipboard_image_bytes_list()
            if b64_list: process_image_step1(b64_list)

    for msg in st.session_state["msg_step1"]:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if st.session_state["workplace_list"]:
        st.success("👍 조직경계가 설정되었습니다! 스크롤을 내려 2단계(배출시설 정의)를 진행하세요.")

# ==========================================
# ⚙️ 2단계: 배출시설 정의 (명세서 3-1)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("⚙️ 2단계: 조직별 배출시설 정의 (명세서 3-1)", expanded=True if st.session_state["workplace_list"] and not st.session_state["facility_list"] else False):
    
    if not st.session_state["workplace_list"]:
        st.warning("⚠️ 1단계를 먼저 완료해주세요.")
    else:
        # 하위조직 선택 드롭다운 만들기
        org_options = []
        for wp in st.session_state["workplace_list"]:
            for sub in wp["하위조직"]:
                org_options.append(f"[{wp['사업장명']}] {sub}")
                
        target_org = st.selectbox("📍 배출시설을 등록할 조직을 선택하세요:", org_options)
        
        sys_prompt_2 = "[SYSTEM COMMAND] 배출시설 자동 맵핑 AI입니다."
        init_prompt_2 = f"""
        이 도면/현황판은 '{target_org}' 조직의 자료야.
        여기서 파악되는 배출시설(예: 0055 일반보일러, 0098 전력사용설비, 0106 연료전지 등)을 추출해서 JSON 배열로 줘.
        [JSON 예시]
        ```json
        [
          {{"조직명": "{target_org}", "배출시설코드": "0055", "배출시설명": "일반 보일러시설", "자체시설명": "온수보일러 1호기", "주요에너지원": "LNG"}},
          {{"조직명": "{target_org}", "배출시설코드": "0098", "배출시설명": "사업장단위 전력사용시설", "자체시설명": "메인수전반", "주요에너지원": "전력"}}
        ]
        ```
        """

        def process_step2(b64_list):
            st.session_state["msg_step2"] = []
            with st.spinner(f"🤖 {target_org}의 배출시설(명세서 3-1)을 파악 중입니다..."):
                ai_msg = run_ai_vision_multi(b64_list, sys_prompt_2, init_prompt_2)
                json_data = extract_json_from_text(ai_msg)
                if json_data:
                    # 기존 리스트에 추가
                    st.session_state["facility_list"].extend(json_data)
                    st.session_state["msg_step2"].append({"role": "assistant", "content": f"✅ 배출시설 식별 완료:\n```json\n{json.dumps(json_data, indent=2, ensure_ascii=False)}\n```"})
                    st.rerun()

        col3, col4 = st.columns([3, 1])
        with col3: up2 = st.file_uploader("📂 시설도면 / 설비대장 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u2")
        with col4:
            st.markdown("<br><br>", unsafe_allow_html=True)
            if st.button("🚀 2단계 배출시설 추출", type="primary", use_container_width=True):
                b64_list = convert_multiple_files_to_image_bytes(up2) if up2 else get_clipboard_image_bytes_list()
                if b64_list: process_step2(b64_list)

        for msg in st.session_state["msg_step2"]:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        
        # 수동 추가 폼
        with st.form("manual_facility"):
            st.write("➕ 수동 배출시설 등록")
            f_code = st.text_input("배출시설코드 (예: 0055)")
            f_name = st.text_input("배출시설명 (예: 일반 보일러시설)")
            f_subname = st.text_input("자체시설명 (예: 온수보일러)")
            if st.form_submit_button("시설 수동 추가"):
                st.session_state["facility_list"].append({"조직명": target_org, "배출시설코드": f_code, "배출시설명": f_name, "자체시설명": f_subname})
                st.rerun()

        if st.session_state["facility_list"]:
            st.success("👍 배출시설이 등록되었습니다! 3단계(영수증 판독)를 진행하세요.")
            st.json(st.session_state["facility_list"])

# ==========================================
# 📂 3단계: 증빙자료 판독 및 산정 (명세서 5)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📂 3단계: 활동자료(증빙) 판독 및 배출량 산정 (명세서 5)", expanded=True):
    
    if not st.session_state["facility_list"]:
        st.warning("⚠️ 2단계에서 배출시설을 먼저 등록하세요.")
    else:
        # 배출시설 드롭다운 만들기
        fac_options = [f"[{f['조직명']}] {f['배출시설코드']}_{f['배출시설명']}({f['자체시설명']})" for f in st.session_state["facility_list"]]
        target_facility = st.selectbox("📍 이 영수증을 귀속시킬 배출시설을 선택하세요:", fac_options)

        sys_prompt_3 = "[SYSTEM COMMAND] KR 온실가스 검증 심사원입니다. 증빙자료의 수치를 정확히 추출해 계산하십시오."
        init_prompt_3 = f"""
        이 증빙자료(고지서/영수증)는 '{target_facility}' 에 속한 자료야.
        문서의 수치를 읽고 [명세서 5 배출활동별 배출량 현황] 양식에 맞춰 아래 JSON을 작성해.
        
        ```json
        {{ 
          "타겟시설": "{target_facility}",
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
                    
                with st.spinner(f"🤖 '{target_facility}' 에 맵핑하며 판독 중입니다..."):
                    ai_msg = run_ai_vision_multi(b64_list, sys_prompt_3, init_prompt_3)
                    st.session_state["msg_step3"].append({"role": "assistant", "content": ai_msg})
                    st.rerun()
            except Exception as e: st.error(f"오류: {e}")

        col5, col6 = st.columns([3, 1])
        with col5: up3 = st.file_uploader("📂 영수증/고지서 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u3")
        with col6:
            st.markdown("<br><br>", unsafe_allow_html=True)
            if st.button("🚀 3단계 활동자료 분석", type="primary", use_container_width=True):
                b64_list = convert_multiple_files_to_image_bytes(up3) if up3 else get_clipboard_image_bytes_list()
                if b64_list: process_step3(up3, b64_list)

        st.divider()
        for msg in st.session_state["msg_step3"]:
            display_text = re.sub(r"```json\n(.*?)\n```", "", msg["content"], flags=re.DOTALL).strip()
            with st.chat_message(msg["role"]): st.markdown(display_text if msg["role"]=="assistant" else msg["content"])
                
        if st.session_state["msg_step3"]:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 이 전표를 구글 클라우드 DB에 확정 저장하기", type="primary"):
                json_data = extract_json_from_text(st.session_state["msg_step3"][-1]["content"])
                
                if json_data and st.session_state["current_file_bytes"]:
                    with st.spinner("☁️ 클라우드에 기록 중..."):
                        drive_link = upload_image_to_drive(st.session_state["current_file_bytes"], "활동자료증빙", st.session_state["current_file_ext"])
                        
                        # 타겟시설 문자열 파싱해서 사업장명과 시설명 분리
                        target_str = json_data.get("타겟시설", "")
                        match = re.match(r"\[(.*?)\] (.*)", target_str)
                        if match:
                            json_data["사업장명"] = match.group(1)
                            json_data["조직(부서/공정)"] = match.group(2)
                        
                        json_data["등록일시"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        json_data["담당 검증원"] = st.session_state["user_id"]
                        json_data["증빙 원본 링크"] = drive_link
                        
                        if save_to_google_sheets(json_data):
                            st.success("🎉 [대성공!] 하위 시설에 완벽하게 맵핑되어 DB에 저장되었습니다!")
                            st.balloons()
                else: st.error("⚠️ AI 데이터 추출 실패")

# ==========================================
# 🗄️ 4단계: NGMS 명세서 출력 (DB 연동)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("🗄️ 4단계: NGMS 명세서 종합 DB 및 엑셀 다운로드", expanded=False):
    st.title("🗄️ NGMS 포맷 인벤토리 통합 DB")
    st.info("💡 저장된 전체 데이터는 '구글 스프레드시트'에서 확인 및 다운로드 가능합니다.")
    
    if st.button("🔄 최신 클라우드 DB 불러오기", use_container_width=True):
        with st.spinner("데이터 동기화 중..."):
            try:
                creds = get_gcp_credentials()
                gc = gspread.authorize(creds)
                sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
                st.session_state["cloud_db_data"] = sheet.get_all_records()
                st.success("✅ 동기화 완료")
            except: st.error("연결 오류")
            
    if "cloud_db_data" in st.session_state and st.session_state["cloud_db_data"]:
        df_cloud = pd.DataFrame(st.session_state["cloud_db_data"])
        st.dataframe(df_cloud, use_container_width=True)
        
        csv = df_cloud.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 인벤토리 명세서 엑셀 다운로드", data=csv, file_name=f"KR_Inventory_{datetime.datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", type="primary")
