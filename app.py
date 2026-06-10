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
            data_dict.get("등록일시", ""), data_dict.get("회사명", ""), data_dict.get("사업장명", ""), 
            data_dict.get("배출시설코드", ""), data_dict.get("배출시설명", ""), data_dict.get("자체시설명", ""),
            data_dict.get("Scope", ""), data_dict.get("배출활동", ""), data_dict.get("사용량", ""), 
            data_dict.get("단위", ""), data_dict.get("배출계수(CO2)", ""), data_dict.get("총배출량(tCO2eq)", ""), 
            data_dict.get("산정근거", ""), data_dict.get("증빙 원본 링크", "")
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
        st.caption("NGMS 3단 계층(회사-사업장-시설) 빌더 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

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

st.title("🏭 KR-GreenAgent : NGMS 명세서 빌더")
st.markdown("**[회사명 ➔ 사업장명 ➔ 배출시설명]** 의 3단 구조와 **[산정 근거 증빙]**을 완벽하게 지원합니다.")

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

def extract_workplace_dicts(ai_text):
    match = re.search(r"WORKPLACE_LIST:\s*(.+)", ai_text)
    result = []
    if match:
        raw_list = match.group(1).split(",")
        for x in raw_list:
            m = re.match(r"\[(.*?)\]\s*(.*)", x.strip())
            if m: result.append({"회사명": m.group(1).strip(), "사업장명": m.group(2).strip()})
    return result

def extract_json_from_text(ai_text):
    try:
        match = re.search(r"```json\n(.*?)\n```", ai_text, re.DOTALL)
        if match: return json.loads(match.group(1))
        return None
    except: return None

# ==========================================
# 🏢 1단계: 조직경계 (회사명 - 사업장명)
# ==========================================
with st.expander("🏢 1단계: 회사명 및 사업장명 조직경계 설정", expanded=True if not st.session_state["workplace_list"] else False):
    t1_1, t1_2, t1_3 = st.tabs(["📂 AI 문서 업로드", "✂️ AI 화면 캡처", "✍️ 수동 직접 입력"])
    
    sys_prompt_1 = "[SYSTEM COMMAND] 당신은 KR 명세서 빌더 AI입니다. 온실가스 관리의 기본인 [회사명-사업장명] 구조를 추출하십시오."
    init_prompt_1 = """
    문서를 분석하여 명세서 1-2(사업장 목록)를 위한 계층 구조를 파악해 줘.
    [매우 중요]
    응답의 제일 마지막 줄에는 반드시 아래 형식으로만 '회사명 - 사업장명'을 묶어서 쉼표로 구분해 적어줘! (다른 말은 쓰지 마!)
    형식 예시: WORKPLACE_LIST: [삼성전자] 수원사업장, [삼성전자] 기흥사업장, [한국선급] 부산본부
    """

    def process_step1(b64_list):
        st.session_state["msg_step1"] = []
        with st.spinner("🤖 문서를 분석하여 회사와 사업장 구조를 생성 중입니다..."):
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
            if st.button("🚀 1단계 회사-사업장 분석", type="primary", use_container_width=True):
                b64_list = convert_multiple_files_to_image_bytes(up1) if up1 else None
                if b64_list: process_step1(b64_list)

    with t1_2:
        st.info("💡 윈도우 캡처(`Shift+Win+S`) 후 아래 버튼을 누르세요.")
        if st.button("📋 캡처본 AI 분석", type="primary", key="btn_c1"):
            b64_list = get_clipboard_image_bytes_list()
            if b64_list: process_step1(b64_list)
            else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
            
    with t1_3:
        with st.form("manual_org_form"):
            st.write("문서 없이 키보드로 [회사명 - 사업장명]을 직접 생성합니다.")
            col_m1, col_m2 = st.columns(2)
            m_comp_name = col_m1.text_input("회사명 (예: 한국선급)")
            m_wp_name = col_m2.text_input("사업장명 (예: 부산본부)")
            if st.form_submit_button("✍️ 조직경계 수동 추가", type="primary"):
                if m_comp_name and m_wp_name:
                    new_org = {"회사명": m_comp_name.strip(), "사업장명": m_wp_name.strip()}
                    if new_org not in st.session_state["workplace_list"]:
                        st.session_state["workplace_list"].append(new_org)
                        st.success(f"✅ [{new_org['회사명']}] {new_org['사업장명']} 등록 완료!")
                        st.rerun()
                else: st.error("빈칸을 모두 채워주세요.")

    # 💡 [삭제 기능 추가] 조직 리스트 관리
    if st.session_state["workplace_list"]:
        st.markdown("#### 📌 현재 등록된 [회사명 - 사업장명] 목록")
        df_org = pd.DataFrame(st.session_state["workplace_list"])
        st.dataframe(df_org, use_container_width=True)
        
        # 삭제 컨트롤
        del_org_idx = st.selectbox("❌ 삭제할 조직을 선택하세요:", range(len(st.session_state["workplace_list"])), format_func=lambda x: f"[{st.session_state['workplace_list'][x]['회사명']}] {st.session_state['workplace_list'][x]['사업장명']}")
        if st.button("🗑️ 선택한 조직 삭제"):
            st.session_state["workplace_list"].pop(del_org_idx)
            st.rerun()

# ==========================================
# ⚙️ 2단계: 배출시설 정의 (명세서 3-1)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("⚙️ 2단계: 사업장별 배출시설 정의 (명세서 3-1)", expanded=True if st.session_state["workplace_list"] and not st.session_state["facility_list"] else False):
    
    if not st.session_state["workplace_list"]: st.warning("⚠️ 1단계 [회사명-사업장명]을 먼저 등록해주세요.")
    else:
        org_options = {i: f"[{wp['회사명']}] {wp['사업장명']}" for i, wp in enumerate(st.session_state["workplace_list"])}
        target_org_idx = st.selectbox("📍 배출시설을 등록할 사업장을 선택하세요:", options=list(org_options.keys()), format_func=lambda x: org_options[x])
        selected_org = st.session_state["workplace_list"][target_org_idx]
        
        t2_1, t2_2, t2_3, t2_4 = st.tabs(["📊 엑셀 대량 업로드", "📂 AI 도면 업로드", "✂️ AI 화면 캡처", "✍️ 수동 직접 입력"])
        
        with t2_1:
            st.info("💡 '배출시설 관리대장(엑셀)'을 올리면 한 번에 등록됩니다. (권장 컬럼: 배출시설코드, 배출시설명, 자체시설명)")
            excel_file = st.file_uploader("📊 배출시설 엑셀/CSV 파일 올리기", type=['xlsx', 'xls', 'csv'])
            if excel_file:
                if st.button("🚀 엑셀 데이터로 시설 대량 등록", type="primary", use_container_width=True):
                    try:
                        if excel_file.name.endswith('.csv'): df_fac = pd.read_csv(excel_file)
                        else: df_fac = pd.read_excel(excel_file)
                        added_count = 0
                        for _, row in df_fac.iterrows():
                            f_code = str(row.get('배출시설코드', row.get('코드', '')))
                            f_name = str(row.get('배출시설명', row.get('시설명', '')))
                            f_subname = str(row.get('자체시설명', row.get('설비명', '')))
                            if f_code != 'nan' and f_name != 'nan':
                                st.session_state["facility_list"].append({
                                    "회사명": selected_org["회사명"], "사업장명": selected_org["사업장명"],
                                    "배출시설코드": f_code.strip(), "배출시설명": f_name.strip(), "자체시설명": f_subname.strip()
                                })
                                added_count += 1
                        st.success(f"🎉 총 {added_count}개 시설 등록 완료!")
                        st.rerun()
                    except Exception as e: st.error(f"오류: {e}")

        sys_prompt_2 = "[SYSTEM COMMAND] 배출시설 맵핑 AI입니다."
        init_prompt_2 = f"""
        이 도면/현황판은 '{selected_org["회사명"]}' 회사의 '{selected_org["사업장명"]}' 사업장 자료야.
        파악되는 배출시설을 추출해서 JSON 배열로 줘.
        [JSON 예시]
        ```json
        [
          {{"배출시설코드": "0055", "배출시설명": "일반 보일러시설", "자체시설명": "온수보일러 1호기"}},
          {{"배출시설코드": "0098", "배출시설명": "사업장단위 전력사용시설", "자체시설명": "메인수전반"}}
        ]
        ```
        """

        def process_step2(b64_list):
            st.session_state["msg_step2"] = []
            with st.spinner(f"🤖 {selected_org['사업장명']}의 배출시설을 파악 중입니다..."):
                ai_msg = run_ai_vision_multi(b64_list, sys_prompt_2, init_prompt_2)
                json_data = extract_json_from_text(ai_msg)
                if json_data:
                    for f in json_data:
                        f["회사명"] = selected_org["회사명"]
                        f["사업장명"] = selected_org["사업장명"]
                        st.session_state["facility_list"].append(f)
                    st.rerun()

        with t2_2:
            col3, col4 = st.columns([3, 1])
            with col3: up2 = st.file_uploader("📂 시설도면 / 설비대장 사진 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u2")
            with col4:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button("🚀 2단계 배출시설 AI 추출", type="primary", use_container_width=True):
                    b64_list = convert_multiple_files_to_image_bytes(up2) if up2 else None
                    if b64_list: process_step2(b64_list)
                    
        with t2_3:
            st.info("💡 윈도우 캡처 후 아래 버튼을 누르세요.")
            if st.button("📋 캡처본 배출시설 AI 추출", type="primary", key="btn_c2"):
                b64_list = get_clipboard_image_bytes_list()
                if b64_list: process_step2(b64_list)
                else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
                
        with t2_4:
            with st.form("manual_facility"):
                st.write("도면 없이 키보드로 [배출시설명]을 직접 등록합니다.")
                col_f1, col_f2, col_f3 = st.columns(3)
                f_code = col_f1.text_input("배출시설코드 (예: 0055)")
                f_name = col_f2.text_input("배출시설명 (예: 일반 보일러시설)")
                f_subname = col_f3.text_input("자체시설명 (예: 온수보일러)")
                if st.form_submit_button("✍️ 배출시설 수동 추가", type="primary"):
                    if f_code and f_name:
                        st.session_state["facility_list"].append({
                            "회사명": selected_org["회사명"], "사업장명": selected_org["사업장명"],
                            "배출시설코드": f_code.strip(), "배출시설명": f_name.strip(), "자체시설명": f_subname.strip()
                        })
                        st.success(f"✅ {f_subname} 시설 등록 완료!")
                        st.rerun()
                    else: st.error("필수 항목(코드, 시설명)을 입력하세요.")

        # 💡 [삭제 기능 추가] 시설 리스트 관리
        if st.session_state["facility_list"]:
            st.markdown("#### 📌 현재 등록된 [회사명-사업장명-배출시설명] 목록")
            st.dataframe(pd.DataFrame(st.session_state["facility_list"]), use_container_width=True)
            
            del_fac_idx = st.selectbox("❌ 삭제할 시설을 선택하세요:", range(len(st.session_state["facility_list"])), format_func=lambda x: f"[{st.session_state['facility_list'][x]['사업장명']}] {st.session_state['facility_list'][x]['자체시설명']}")
            if st.button("🗑️ 선택한 배출시설 삭제"):
                st.session_state["facility_list"].pop(del_fac_idx)
                st.rerun()

# ==========================================
# 📂 3단계: 활동자료(증빙) 판독 및 산정 (명세서 5)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📂 3단계: 활동자료 증빙 판독 및 산정근거 분석 (명세서 5)", expanded=True):
    
    if not st.session_state["facility_list"]: st.warning("⚠️ 2단계에서 배출시설을 먼저 등록하세요.")
    else:
        fac_options = {i: f"[{f['회사명']}] {f['사업장명']} - {f['배출시설코드']}_{f['배출시설명']}({f['자체시설명']})" for i, f in enumerate(st.session_state["facility_list"])}
        target_fac_idx = st.selectbox("📍 전표를 귀속시킬 '회사/사업장/시설' 라인을 선택하세요:", options=list(fac_options.keys()), format_func=lambda x: fac_options[x])
        selected_fac = st.session_state["facility_list"][target_fac_idx]

        t3_1, t3_2, t3_3 = st.tabs(["📂 AI 영수증 업로드", "✂️ AI 화면 캡처", "✍️ 수동 전표 직접 입력"])
        
        sys_prompt_3 = "[SYSTEM COMMAND] KR 온실가스 검증 심사원입니다. 증빙자료에 기재된 단가, 수량, 결제금액 등을 꼼꼼히 역산하여 계산 식(산정 근거)을 명확하게 제시하십시오."
        init_prompt_3 = f"""
        이 증빙자료(고지서/영수증)는 '{fac_options[target_fac_idx]}' 에 속한 자료야.
        문서의 수치를 읽고 아래 3단계를 거쳐 완벽하게 분석해 줘.
        
        ### 🔍 [1] 증빙 분석 및 산정 근거 (Audit Trail)
        - 증빙 종류: (예: 주유소 영수증, 한전 고지서)
        - 유종/에너지원 판별 근거: (예: 영수증에 '경유'라고 적혀 있음)
        - **수치 산정 식 (가장 중요)**: 
          * 영수증의 경우: 총 결제금액(원) ÷ 단가(원/L) = 최종 사용량(L) 도출 과정 상세히 적을 것!
        
        ### 📝 [2] 명세서 5 배출활동별 배출량 현황
        | 배출활동(연료) | 연간 사용량 | 단위 | 적용 배출계수 | 산정 배출량(tCO2eq) |
        |---|---|---|---|---|
        
        ### 💾 [3] DB 저장을 위한 JSON 데이터
        ```json
        {{ 
          "Scope": "Scope 1 또는 2", 
          "배출활동": "경유, 전력, LNG 등", 
          "사용량": (산출된 최종수치), 
          "단위": "L, kWh 등", 
          "배출계수(CO2)": (계수), 
          "총배출량(tCO2eq)": (계산값),
          "산정근거": "(예: 총 50,000원 주유, 단가 1,500원/L 적용하여 33.3L 산출)"
        }}
        ```
        """

        def process_step3(up_files, b64_list):
            st.session_state["msg_step3"] = []
            try:
                if up_files:
                    first = up_files[0] if isinstance(up_files, list) else up_files
                    st.session_state["current_file_bytes"] = first.getvalue()
                    st.session_state["current_file_ext"] = ".pdf" if first.name.lower().endswith('.pdf') else ".jpg"
                else:
                    st.session_state["current_file_bytes"] = base64.b64decode(b64_list[0])
                    st.session_state["current_file_ext"] = ".jpg"
                    
                with st.spinner(f"🤖 '{selected_fac['사업장명']}-{selected_fac['자체시설명']}' 에 맵핑하며 산정근거를 분석 중입니다..."):
                    ai_msg = run_ai_vision_multi(b64_list, sys_prompt_3, init_prompt_3)
                    st.session_state["msg_step3"].append({"role": "assistant", "content": ai_msg})
                    st.rerun()
            except Exception as e: st.error(f"오류: {e}")

        with t3_1:
            col5, col6 = st.columns([3, 1])
            with col5: up3 = st.file_uploader("📂 영수증/고지서 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u3")
            with col6:
                st.markdown("<br><br>", unsafe_allow_html=True)
                if st.button("🚀 3단계 활동자료 및 산정근거 분석", type="primary", use_container_width=True):
                    b64_list = convert_multiple_files_to_image_bytes(up3) if up3 else None
                    if b64_list: process_step3(up3, b64_list)

        with t3_2:
            st.info("💡 윈도우 캡처(Shift+Win+S) 후 아래 버튼을 누르세요.")
            if st.button("📋 캡처본 전표 AI 분석", type="primary", key="btn_c3"):
                b64_list = get_clipboard_image_bytes_list()
                if b64_list: process_step3(None, b64_list)
                else: st.error("⚠️ 클립보드에 이미지가 없습니다!")
                
        with t3_3:
            with st.form("manual_activity"):
                st.write("📝 증빙이 없거나 수동으로 입력할 데이터를 작성합니다.")
                c_a1, c_a2, c_a3 = st.columns(3)
                m_scope = c_a1.selectbox("Scope 분류", ["Scope 1", "Scope 2", "Scope 3"])
                m_activity = c_a2.text_input("배출활동 (예: 경유, 전력)")
                m_usage = c_a3.number_input("사용량", min_value=0.0, format="%.2f")
                
                c_a4, c_a5, c_a6 = st.columns(3)
                m_unit = c_a4.text_input("단위 (예: L, kWh)")
                m_factor = c_a5.number_input("배출계수", min_value=0.0, format="%.4f")
                m_emission = c_a6.number_input("총 산정 배출량(tCO2eq)", min_value=0.0, format="%.2f")
                
                m_reason = st.text_input("산정 근거 (예: 주유 영수증 단가 역산, 엑셀 집계본 등)")
                
                if st.form_submit_button("✍️ 수동 전표 DB 확정 등록", type="primary"):
                    if m_activity:
                        manual_data = {
                            "등록일시": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "담당 검증원": st.session_state["user_id"],
                            "Scope": m_scope, "배출활동": m_activity, "사용량": m_usage, "단위": m_unit, 
                            "배출계수(CO2)": m_factor, "총배출량(tCO2eq)": m_emission, "산정근거": m_reason, "증빙 원본 링크": "수동 입력"
                        }
                        manual_data.update(selected_fac)
                        save_to_google_sheets(manual_data)
                        st.session_state["inventory_db"].append(manual_data)
                        st.success("🎉 수동 전표가 DB에 완벽하게 저장되었습니다!")
                        st.rerun()
                    else: st.error("필수 항목을 입력하세요.")

        st.divider()
        for msg in st.session_state["msg_step3"]:
            display_text = re.sub(r"```json\n(.*?)\n```", "", msg["content"], flags=re.DOTALL).strip()
            with st.chat_message("assistant" if msg["role"] == "assistant" else "user"): st.markdown(display_text if msg["role"] == "assistant" else msg["content"])
                
        if st.session_state["msg_step3"]:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 위 산정근거와 전표를 로컬/클라우드 DB에 확정 저장하기", type="primary"):
                json_data = extract_json_from_text(st.session_state["msg_step3"][-1]["content"])
                
                if json_data and st.session_state["current_file_bytes"]:
                    with st.spinner("☁️ 클라우드에 기록 중..."):
                        drive_link = upload_image_to_drive(st.session_state["current_file_bytes"], "활동자료증빙", st.session_state["current_file_ext"])
                        
                        json_data.update(selected_fac)
                        json_data["등록일시"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        json_data["담당 검증원"] = st.session_state["user_id"]
                        json_data["증빙 원본 링크"] = drive_link
                        
                        save_to_google_sheets(json_data)
                        st.session_state["inventory_db"].append(json_data)
                        st.success("🎉 [대성공!] 산정 근거와 함께 명세서 DB에 완벽하게 저장되었습니다!")
                        st.balloons()
                else: st.error("⚠️ AI 데이터 추출 실패")
                
        if st.session_state.get("current_file_bytes"):
            if user_input_3 := st.chat_input("추가 지시 (예: 단가 계산이 틀렸어. 금액 5만원 나누기 단가 1500원으로 다시 계산해줘)"):
                st.session_state["msg_step3"].append({"role": "user", "content": user_input_3})
                with st.spinner("🤖 산정 근거 수정 중..."):
                    content_list = [{"type": "text", "text": "이전 문서야."}]
                    b64_image = base64.b64encode(st.session_state["current_file_bytes"]).decode('utf-8')
                    content_list.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}})
                    
                    api_messages = [{"role": "system", "content": sys_prompt_3}, {"role": "user", "content": content_list}]
                    for m in st.session_state["msg_step3"]: api_messages.append({"role": m["role"], "content": m["content"]})
                    api_messages.append({"role": "user", "content": user_input_3 + "\n(반드시 수정된 결과도 ```json 묶음으로 출력해!)"})
                    
                    reply = client.chat.completions.create(model="gpt-4o", messages=api_messages, temperature=0.0).choices[0].message.content
                    st.session_state["msg_step3"].append({"role": "assistant", "content": reply})
                    st.rerun()

        # 💡 [삭제 기능 추가] 등록된 전표 리스트 관리
        if st.session_state["inventory_db"]:
            st.markdown("#### 📌 현재 로컬 세션에 등록된 전표(활동자료) 목록")
            df_inv = pd.DataFrame(st.session_state["inventory_db"])
            st.dataframe(df_inv[["사업장명", "자체시설명", "배출활동", "사용량", "산정근거"]], use_container_width=True)
            
            del_inv_idx = st.selectbox("❌ 로컬 목록에서 삭제할 전표를 선택하세요:", range(len(st.session_state["inventory_db"])), format_func=lambda x: f"[{st.session_state['inventory_db'][x]['자체시설명']}] {st.session_state['inventory_db'][x]['배출활동']} ({st.session_state['inventory_db'][x]['사용량']})")
            if st.button("🗑️ 선택한 전표 로컬에서 삭제"):
                st.session_state["inventory_db"].pop(del_inv_idx)
                st.success("로컬 세션에서 삭제되었습니다. (구글 클라우드 DB는 수동으로 삭제해야 합니다.)")
                st.rerun()

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
                <p><b>■ 담당 검증원 :</b> {st.session_state["user_id"]}</p>
                <p><b>■ 총 온실가스 배출량 :</b> <span style="color:red; font-size:18px;"><b>{total_co2:,.2f} tCO2-eq</b></span></p>
            </div>

            <h2>5. 배출활동별 배출량 현황 (세부 명세)</h2>
            <table>
                <thead>
                    <tr>
                        <th>연번</th>
                        <th>회사명</th>
                        <th>사업장명</th>
                        <th>배출시설명(자체명)</th>
                        <th>배출활동(연료)</th>
                        <th>사용량</th>
                        <th>단위</th>
                        <th>배출량(tCO2eq)</th>
                        <th>산정 근거 (Audit Trail)</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for i, row in df.iterrows():
            report_html += f"""
                    <tr>
                        <td>{i+1}</td>
                        <td>{row.get('회사명','')}</td>
                        <td>{row.get('사업장명','')}</td>
                        <td>{row.get('배출시설명','')} ({row.get('자체시설명','')})</td>
                        <td>{row.get('배출활동','')}</td>
                        <td>{row.get('사용량','')}</td>
                        <td>{row.get('단위','')}</td>
                        <td><b>{row.get('총배출량(tCO2eq)','')}</b></td>
                        <td style="text-align:left;">{row.get('산정근거','')}</td>
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
