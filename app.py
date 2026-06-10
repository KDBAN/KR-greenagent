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
        
        # 💡 원래 확장자(PDF/JPG 등)를 유지해서 원본 그대로 드라이브에 저장
        drive_file_name = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_name}{file_extension}"
        file_metadata = {'name': drive_file_name, 'parents': [GOOGLE_DRIVE_FOLDER_ID]}
        
        # Mime Type 설정
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
        row_data = [data_dict.get("담당 검증원", ""), data_dict.get("등록일시", ""), data_dict.get("사업장명", ""), data_dict.get("Scope", ""), data_dict.get("배출활동", ""), data_dict.get("사용량", ""), data_dict.get("단위", ""), data_dict.get("배출계수", ""), data_dict.get("배출량(tCO2eq)", ""), data_dict.get("증빙 원본 링크", "")]
        sheet.append_row(row_data)
        return True
    except Exception as e: return False

st.set_page_config(page_title="KR-GreenAgent", page_icon="🏭", layout="wide")

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_id" not in st.session_state: st.session_state["user_id"] = ""

if not st.session_state["logged_in"]:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.title("🔐 KR-GreenAgent")
        st.caption("구글 클라우드 연동 온실가스 검증 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

if "boundary_context" not in st.session_state: st.session_state["boundary_context"] = ""
if "workplace_list" not in st.session_state: st.session_state["workplace_list"] = []
if "messages_step1" not in st.session_state: st.session_state["messages_step1"] = []
if "messages_step2" not in st.session_state: st.session_state["messages_step2"] = []
if "image_context_step1" not in st.session_state: st.session_state["image_context_step1"] = [] # 여러 장 지원으로 리스트로 변경
if "image_context_step2" not in st.session_state: st.session_state["image_context_step2"] = [] # 여러 장 지원으로 리스트로 변경
if "current_file_bytes" not in st.session_state: st.session_state["current_file_bytes"] = None
if "current_file_ext" not in st.session_state: st.session_state["current_file_ext"] = ".jpg"

st.sidebar.title("🏭 KR-GreenAgent")
st.sidebar.success(f"👤 **{st.session_state['user_id']}** 검증원 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.clear()
    st.rerun()

st.title("🏭 KR-GreenAgent 클라우드 통합 플랫폼")

# --- 💡 [핵심] PDF의 "모든 페이지"를 이미지 바이트 리스트로 변환하는 함수 ---
def convert_to_image_bytes_list(uploaded_file):
    image_bytes_list = []
    try:
        if uploaded_file.name.lower().endswith('.pdf'):
            pdf_document = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            # PDF의 모든 페이지를 순회하며 캡처
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                image_bytes_list.append(base64.b64encode(buf.getvalue()).decode('utf-8'))
            return image_bytes_list
        else:
            img = Image.open(uploaded_file).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            image_bytes_list.append(base64.b64encode(buf.getvalue()).decode('utf-8'))
            return image_bytes_list
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
        return 
