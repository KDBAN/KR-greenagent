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
        row_data = [data_dict.get("담당 검증원", ""), data_dict.get("등록일시", ""), data_dict.get("사업장명", ""), data_dict.get("Scope", ""), data_dict.get("배출활동", ""), data_dict.get("사용량", ""), data_dict.get("단위", ""), data_dict.get("배출계수", ""), data_dict.get("배출량(tCO2eq)", ""), data_dict.get("증빙 원본 링크", ""), data_dict.get("AI 코멘트", "")]
        sheet.append_row(row_data)
        return True
    except Exception as e: return False

st.set_page_config(page_title="KR-GreenAgent", page_icon="🏭", layout="wide")

# ==========================================
# 🔐 로그인
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_id" not in st.session_state: st.session_state["user_id"] = ""

if not st.session_state["logged_in"]:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 KR-GreenAgent")
        st.caption("기업용 정형 온실가스 검증 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

# ==========================================
# 🗄️ 세션 초기화
# ==========================================
if "workplace_list" not in st.session_state: st.session_state["workplace_list"] = []
# 💡 2단계 폼 채우기용 세션 변수들
if "parsed_data" not in st.session_state: st.session_state["parsed_data"] = {}
if "monthly_table" not in st.session_state: st.session_state["monthly_table"] = ""
if "current_file_bytes" not in st.session_state: st.session_state["current_file_bytes"] = None
if "current_file_ext" not in st.session_state: st.session_state["current_file_ext"] = ".jpg"

st.sidebar.title("🏭 KR-GreenAgent")
st.sidebar.success(f"👤 **{st.session_state['user_id']}** 검증원 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.clear()
    st.rerun()

st.title("🏭 KR-GreenAgent ERP 시스템")

# ==========================================
# 💡 [공통] AI 함수
# ==========================================
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
    except Exception as e:
        st.error(f"파일 변환 오류: {e}")
        return []

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
        return {}
    except: return {}

# ==========================================
# 🏢 1단계: 조직경계 AI 설정 (ERP 스타일)
# ==========================================
with st.expander("🏢 1단계: 기초 마스터 데이터 (조직경계 설정)", expanded=True):
    col1, col2 = st.columns([3, 1])
    with col1: uploaded_files_1 = st.file_uploader("📂 사업자등록증/조직도 업로드", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="up1")
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 조직 마스터 데이터 스캔", type="primary", use_container_width=True):
            b64_list = convert_multiple_files_to_image_bytes(uploaded_files_1) if uploaded_files_1 else get_clipboard_image_bytes_list()
            if b64_list:
                with st.spinner("🤖 스캔 중..."):
                    sys_p1 = "당신은 정보 추출 AI입니다. 사업자등록증이나 조직도를 보고 하위 사업장 목록을 파악하세요."
                    init_p1 = "문서를 보고 조직경계를 파악해. 응답은 무조건 순수 JSON 배열(리스트) 형태로만 뱉어. 예시: [\"[본사] 일반\", \"[울산공장] 생산팀\"]"
                    ai_msg = run_ai_vision_multi(b64_list, sys_p1, init_prompt_1 := init_p1)
                    try:
                        workplaces = json.loads(ai_msg)
                        if isinstance(workplaces, list):
                            st.session_state["workplace_list"] = workplaces
                            st.success("✅ 조직 마스터 데이터 등록 완료!")
                    except: st.error("추출 실패. 명확한 이미지를 올려주세요.")
            else: st.warning("파일이나 클립보드 이미지가 필요합니다.")

    if st.session_state["workplace_list"]:
        st.write("📌 **현재 등록된 사업장 목록**")
        st.write(st.session_state["workplace_list"])
        
        # 사용자가 직접 추가/삭제 가능하게
        new_wp = st.text_input("➕ 수동으로 사업장 추가하기")
        if st.button("추가", key="add_wp"):
            if new_wp: 
                st.session_state["workplace_list"].append(new_wp)
                st.rerun()

# ==========================================
# 📂 2단계: 증빙자료 판독 및 ERP 폼 입력
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📂 2단계: 활동자료 전표 입력 (증빙 판독)", expanded=True):
    
    col_up1, col_up2 = st.columns([3, 1])
    with col_up1: uploaded_files_2 = st.file_uploader("📂 영수증/고지서 업로드", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="up2")
    with col_up2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🚀 증빙자료 스캔 및 폼 자동채우기", type="primary", use_container_width=True):
            b64_list = convert_multiple_files_to_image_bytes(uploaded_files_2) if uploaded_files_2 else get_clipboard_image_bytes_list()
            if b64_list:
                if uploaded_files_2:
                    first = uploaded_files_2[0] if isinstance(uploaded_files_2, list) else uploaded_files_2
                    st.session_state["current_file_bytes"] = first.getvalue()
                    st.session_state["current_file_ext"] = ".pdf" if first.name.lower().endswith('.pdf') else ".jpg"
                else:
                    st.session_state["current_file_bytes"] = base64.b64decode(b64_list[0])
                    st.session_state["current_file_ext"] = ".jpg"
                    
                with st.spinner("🤖 수치 추출 중..."):
                    sys_p2 = "당신은 KR 온실가스 ERP 자동입력 봇입니다. 텍스트와 수치를 완벽히 추출하십시오."
                    init_p2 = """
                    여러 장의 영수증/고지서를 종합 분석하여, 반드시 아래 2가지를 출력해.
                    
                    1. 월별 내역 (마크다운 표)
                    | 월 | 활동자료 | 사용량 | 비고 |
                    |---|---|---|---|
                    
                    2. 종합 합산 결과를 담은 JSON 데이터 (반드시 ```json 으로 감쌀 것)
                    ```json
                    {
                        "Scope": "Scope 1 또는 2",
                        "배출활동": "전력, 무연휘발유 등",
                        "사용량": 1500,
                        "단위": "kWh, L 등",
                        "배출계수": 0.4781,
                        "배출량": 0.71,
                        "AI 코멘트": "모니터링 유형 A-1으로 추정됨. 4월 결측치 존재."
                    }
                    ```
                    """
                    ai_msg = run_ai_vision_multi(b64_list, sys_p2, init_prompt_2 := init_p2)
                    
                    # 마크다운 표 부분(월별 내역) 추출
                    markdown_part = re.sub(r"```json\n(.*?)\n```", "", ai_msg, flags=re.DOTALL).strip()
                    st.session_state["monthly_table"] = markdown_part
                    
                    # JSON 부분 추출해서 세션에 꽂아넣기
                    json_data = extract_json_from_text(ai_msg)
                    if json_data:
                        st.session_state["parsed_data"] = json_data
                    
                    st.success("✅ 스캔 완료! 아래 입력 폼을 확인하고 확정해 주세요.")
            else: st.warning("파일이나 클립보드 이미지가 필요합니다.")

    st.divider()
    
    # 💡 [UX 혁신] 채팅창 대신 ERP 스타일의 정형화된 입력 폼(Form) 제공!
    if st.session_state["monthly_table"]:
        st.markdown("### 📊 월별 내역 상세")
        st.markdown(st.session_state["monthly_table"])
        
    st.markdown("### 📝 전표 입력 확인 (수정 가능)")
    
    # 폼 영역 시작
    with st.form("inventory_form"):
        col_f1, col_f2, col_f3 = st.columns(3)
        
        options = st.session_state["workplace_list"] if st.session_state["workplace_list"] else ["본점"]
        
        # 텍스트 박스에 AI가 분석한 값을 기본값(value)으로 쏙쏙 넣어줍니다!
        f_workplace = col_f1.selectbox("사업장명", options)
        f_scope = col_f2.text_input("Scope 분류", value=st.session_state["parsed_data"].get("Scope", ""))
        f_activity = col_f3.text_input("배출활동(에너지원)", value=st.session_state["parsed_data"].get("배출활동", ""))
        
        col_f4, col_f5, col_f6 = st.columns(3)
        f_amount = col_f4.number_input("연간 총 사용량", value=float(st.session_state["parsed_data"].get("사용량", 0.0)), format="%.2f")
        f_unit = col_f5.text_input("단위", value=st.session_state["parsed_data"].get("단위", ""))
        f_factor = col_f6.number_input("적용 배출계수", value=float(st.session_state["parsed_data"].get("배출계수", 0.0)), format="%.4f")
        
        f_emission = st.number_input("총 산정 배출량 (tCO2eq)", value=float(st.session_state["parsed_data"].get("배출량", 0.0)), format="%.2f")
        f_comment = st.text_area("검증원 코멘트 (AI 제안)", value=st.session_state["parsed_data"].get("AI 코멘트", ""))
        
        submitted = st.form_submit_button("💾 폼 데이터로 구글 클라우드 DB 확정 저장하기", type="primary", use_container_width=True)
        
        if submitted:
            if st.session_state["current_file_bytes"]:
                with st.spinner("☁️ 구글 클라우드에 전표를 기록 중입니다..."):
                    drive_link = upload_image_to_drive(st.session_state["current_file_bytes"], f_workplace, st.session_state["current_file_ext"])
                    
                    final_data = {
                        "등록일시": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "담당 검증원": st.session_state["user_id"],
                        "사업장명": f_workplace,
                        "Scope": f_scope,
                        "배출활동": f_activity,
                        "사용량": f_amount,
                        "단위": f_unit,
                        "배출계수": f_factor,
                        "배출량(tCO2eq)": f_emission,
                        "증빙 원본 링크": drive_link,
                        "AI 코멘트": f_comment
                    }
                    
                    if save_to_google_sheets(final_data):
                        st.success("🎉 [대성공!] 전표가 클라우드 DB에 완벽하게 저장되었습니다!")
                        st.balloons()
                        # 저장 후 폼 비우기
                        st.session_state["parsed_data"] = {}
                        st.session_state["monthly_table"] = ""
            else:
                st.error("⚠️ 증빙 원본 파일이 없습니다.")

# ==========================================
# 🗄️ 3단계: 내 인벤토리 명세서 종합 관리 (DB 연동)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("🗄️ 3단계: 내 인벤토리 명세서 DB (구글 시트 연동 및 엑셀 다운로드)", expanded=False):
    st.title("🗄️ 온실가스 인벤토리(명세서) 통합 DB")
    st.markdown(f"1, 2단계를 거쳐 **구글 클라우드 시트**에 실시간으로 적재된 최종 명세서 데이터입니다.")
    
    col_db1, col_db2 = st.columns([4, 1])
    with col_db2:
        # 버튼을 누르면 구글 시트에서 최신 데이터를 싹 긁어옵니다.
        if st.button("🔄 최신 DB 데이터 불러오기", use_container_width=True, key="fetch_db"):
            with st.spinner("구글 시트에서 데이터를 가져오는 중..."):
                try:
                    creds = get_gcp_credentials()
                    gc = gspread.authorize(creds)
                    sheet = gc.open_by_key(GOOGLE_SHEET_ID).sheet1
                    # 시트의 모든 데이터를 리스트로 가져오기
                    all_data = sheet.get_all_records()
                    st.session_state["cloud_db_data"] = all_data
                    st.success("✅ 최신 데이터를 불러왔습니다.")
                except Exception as e:
                    st.error("데이터를 불러오지 못했습니다. (권한 또는 연결 오류)")
    
    if "cloud_db_data" in st.session_state and st.session_state["cloud_db_data"]:
        # 판다스 데이터프레임으로 예쁘게 엑셀처럼 보여줌
        df_cloud = pd.DataFrame(st.session_state["cloud_db_data"])
        st.dataframe(df_cloud, use_container_width=True)
        
        # 종합 대시보드 요약 (배출량 tCO2eq 합산)
        st.markdown("### 📊 배출량 요약 대시보드")
        try:
            # 엑셀에 적힌 문자를 숫자로 강제 변환 후 합산
            total_emission = pd.to_numeric(df_cloud["배출량(tCO2eq)"], errors='coerce').sum()
            colA, colB = st.columns(2)
            colA.metric(label="누적 배출량 합계", value=f"{total_emission:,.2f} tCO2eq")
            colB.metric(label="총 등록된 전표 건수", value=f"{len(df_cloud)} 건")
        except:
            st.info("합계를 계산할 데이터가 부족합니다.")
        
        # 💡 [핵심] CSV(엑셀) 다운로드 버튼
        csv = df_cloud.to_csv(index=False).encode('utf-8-sig') # 한글 깨짐 방지 utf-8-sig
        st.download_button(
            label="📥 인벤토리 명세서 전체 다운로드 (Excel/CSV)",
            data=csv,
            file_name=f"KR_GreenAgent_Inventory_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            type="primary"
        )
    else:
        st.info("💡 우측 상단의 [🔄 최신 DB 데이터 불러오기] 버튼을 눌러주세요.")
