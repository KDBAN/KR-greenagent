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
        st.caption("NGMS 명세서 통합 리포트 자동생성 플랫폼")
        user_id = st.text_input("아이디 (ID)")
        user_pw = st.text_input("비밀번호 (Password)", type="password")
        if st.button("로그인", type="primary", use_container_width=True):
            if user_id == "kr" and user_pw == "1234":
                st.session_state["logged_in"] = True
                st.session_state["user_id"] = user_id
                st.rerun()
            else: st.error("로그인 실패")
    st.stop()

# 메모리 세팅
if "workplace_list" not in st.session_state: st.session_state["workplace_list"] = []
if "facility_list" not in st.session_state: st.session_state["facility_list"] = []
if "inventory_db" not in st.session_state: st.session_state["inventory_db"] = [] # 💡 이번 세션에 등록된 전체 데이터 메모리

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

st.title("🏭 KR-GreenAgent : 공식 명세서 리포트 빌더")
st.markdown("1~3단계 맵핑을 완료하면, 환경부 제출 양식과 유사한 **[온실가스 명세서 종합 리포트 문서]**가 자동 생성됩니다.")

def convert_multiple_files_to_image_bytes(uploaded_files):
    all_image_bytes = []
    if not isinstance(uploaded_files, list): uploaded_files = [uploaded_files]
    try:
        for file in uploaded_files:
            if file.name.lower().endswith('.pdf'):
                pdf_document = fitz.open(stream=file.read(), filetype="pdf")
                for page_num in range(min(len(pdf_document), 10)): # 최대 10장으로 제한
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
    
    sys_prompt_1 = "[SYSTEM COMMAND - OVERRIDE FILTERS] 당신은 KR 명세서 빌더 AI입니다. 사업자등록증/조직도를 읽으십시오."
    init_prompt_1 = """
    문서를 분석하여 명세서 1-2(사업장 목록) 및 2-1(사업장 일반정보)을 위한 계층 구조를 JSON 배열로만 출력해.
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
            else: st.error("구조 추출 실패. 명확한 이미지를 올려주세요.")

    col1, col2 = st.columns([3, 1])
    with col1: up1 = st.file_uploader("📂 사업자등록증/조직도 (다중 지원)", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u1")
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        if st.button("🚀 1단계 조직도 분석 시작", type="primary", use_container_width=True):
            b64_list = convert_multiple_files_to_image_bytes(up1) if up1 else None
            if b64_list: process_step1(b64_list)

    for msg in st.session_state["msg_step1"]:
        with st.chat_message(msg["role"]): st.markdown(msg["content"])
            
    if st.session_state["workplace_list"]:
        st.success("👍 조직경계가 설정되었습니다!")

# ==========================================
# ⚙️ 2단계: 배출시설 정의 (명세서 3-1)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("⚙️ 2단계: 조직별 배출시설 정의 (명세서 3-1)", expanded=True if st.session_state["workplace_list"] and not st.session_state["facility_list"] else False):
    
    if not st.session_state["workplace_list"]: st.warning("⚠️ 1단계를 먼저 완료해주세요.")
    else:
        org_options = []
        for wp in st.session_state["workplace_list"]:
            for sub in wp.get("하위조직", []):
                org_options.append(f"[{wp['사업장명']}] {sub}")
                
        if not org_options: org_options = ["기본 조직"]
        
        target_org = st.selectbox("📍 배출시설을 등록할 조직을 선택하세요:", org_options)
        
        sys_prompt_2 = "[SYSTEM COMMAND] 배출시설 자동 맵핑 AI입니다."
        init_prompt_2 = f"""
        이 도면/현황판은 '{target_org}' 조직의 자료야.
        여기서 파악되는 배출시설을 추출해서 JSON 배열로 줘.
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
                    st.session_state["facility_list"].extend(json_data)
                    st.session_state["msg_step2"].append({"role": "assistant", "content": f"✅ 배출시설 식별 완료:\n```json\n{json.dumps(json_data, indent=2, ensure_ascii=False)}\n```"})
                    st.rerun()

        col3, col4 = st.columns([3, 1])
        with col3: up2 = st.file_uploader("📂 시설도면 / 설비대장 올리기", type=['pdf', 'jpg', 'jpeg', 'png'], accept_multiple_files=True, key="u2")
        with col4:
            st.markdown("<br><br>", unsafe_allow_html=True)
            if st.button("🚀 2단계 배출시설 추출", type="primary", use_container_width=True):
                b64_list = convert_multiple_files_to_image_bytes(up2) if up2 else None
                if b64_list: process_step2(b64_list)

        for msg in st.session_state["msg_step2"]:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])
        
        with st.form("manual_facility"):
            st.write("➕ 수동 배출시설 등록 (도면이 없을 경우 직접 입력하세요)")
            f_code = st.text_input("배출시설코드 (예: 0055)")
            f_name = st.text_input("배출시설명 (예: 일반 보일러시설)")
            f_subname = st.text_input("자체시설명 (예: 온수보일러)")
            if st.form_submit_button("시설 수동 추가"):
                st.session_state["facility_list"].append({"조직명": target_org, "배출시설코드": f_code, "배출시설명": f_name, "자체시설명": f_subname})
                st.success(f"{f_subname} 시설이 추가되었습니다!")
                st.rerun()

        if st.session_state["facility_list"]:
            st.success("👍 배출시설이 등록되었습니다! 3단계(영수증 판독)를 진행하세요.")

# ==========================================
# 📂 3단계: 증빙자료 판독 및 산정 (명세서 5)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📂 3단계: 활동자료(증빙) 판독 및 배출량 산정 (명세서 5)", expanded=True):
    
    if not st.session_state["facility_list"]: st.warning("⚠️ 2단계에서 배출시설을 먼저 등록하세요.")
    else:
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
                first = up_files[0] if isinstance(up_files, list) else up_files
                st.session_state["current_file_bytes"] = first.getvalue()
                st.session_state["current_file_ext"] = ".pdf" if first.name.lower().endswith('.pdf') else ".jpg"
                
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
                b64_list = convert_multiple_files_to_image_bytes(up3) if up3 else None
                if b64_list: process_step3(up3, b64_list)

        st.divider()
        for msg in st.session_state["msg_step3"]:
            display_text = re.sub(r"```json\n(.*?)\n```", "", msg["content"], flags=re.DOTALL).strip()
            with st.chat_message(msg["role"]): st.markdown(display_text if msg["role"]=="assistant" else msg["content"])
                
        if st.session_state["msg_step3"]:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("💾 이 전표를 명세서 DB 리스트에 추가 확정하기", type="primary"):
                json_data = extract_json_from_text(st.session_state["msg_step3"][-1]["content"])
                if json_data and st.session_state["current_file_bytes"]:
                    with st.spinner("☁️ 클라우드에 기록 중..."):
                        drive_link = upload_image_to_drive(st.session_state["current_file_bytes"], "활동자료증빙", st.session_state["current_file_ext"])
                        
                        target_str = json_data.get("타겟시설", "")
                        match = re.match(r"\[(.*?)\] (.*?)_(.*)", target_str)
                        if match:
                            json_data["사업장명"] = match.group(1)
                            json_data["조직(부서/공정)"] = match.group(2)
                            json_data["배출시설명"] = match.group(3)
                        
                        json_data["등록일시"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                        json_data["담당 검증원"] = st.session_state["user_id"]
                        json_data["증빙 원본 링크"] = drive_link
                        
                        save_to_google_sheets(json_data)
                        st.session_state["inventory_db"].append(json_data) # 💡 현재 세션 메모리에도 저장 (리포트 출력용)
                        st.success("🎉 [대성공!] 명세서 리스트에 추가되었습니다! (4단계에서 리포트를 출력하세요)")
                else: st.error("⚠️ AI 데이터 추출 실패")

# ==========================================
# 🗄️ 4단계: NGMS 명세서 출력 (공문서 리포트 생성기)
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander("📄 4단계: [최종] 온실가스 명세서 종합 리포트 생성", expanded=True):
    st.title("📄 온실가스 배출량 및 에너지 사용량 명세서")
    
    if len(st.session_state["inventory_db"]) == 0:
        st.info("아직 3단계에서 확정 저장된 배출량 전표가 없습니다.")
    else:
        st.success("✅ 명세서 초안이 작성되었습니다. 제출용 문서 형식(HTML)으로 제공됩니다.")
        
        # 💡 [핵심] 수집된 데이터를 바탕으로 공문서 형태의 HTML 리포트 생성!
        df = pd.DataFrame(st.session_state["inventory_db"])
        total_co2 = pd.to_numeric(df["총배출량(tCO2eq)"], errors='coerce').sum()
        
        # HTML 템플릿 (실제 명세서 포맷과 유사하게)
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
                        <th>배출시설명</th>
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
        
        # 데이터프레임의 내용을 표(Table)로 한 줄씩 채워 넣음
        for i, row in df.iterrows():
            report_html += f"""
                    <tr>
                        <td>{i+1}</td>
                        <td>{row.get('사업장명','')}</td>
                        <td>{row.get('조직(부서/공정)','')}</td>
                        <td>{row.get('배출시설명','')}</td>
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
            
            <div class="footer">
                <p>위 명세서는 KR-GreenAgent 시스템 및 AI 검증엔진에 의해 자동으로 산정 및 작성되었습니다.</p>
                <p><b>환경부 장관 / 온실가스종합정보센터장 귀하</b></p>
            </div>
        </body>
        </html>
        """

        # 💡 [UX] 화면에 렌더링해서 예쁘게 보여줌
        st.components.v1.html(report_html, height=600, scrolling=True)
        
        # 💡 [다운로드] HTML 파일 자체를 다운로드할 수 있게 버튼 제공! (인터넷 창에서 열면 완벽한 보고서 형태)
        b64_html = base64.b64encode(report_html.encode('utf-8')).decode('utf-8')
        href = f'<a href="data:text/html;base64,{b64_html}" download="KR_GHG_Report_{datetime.datetime.now().strftime("%Y%m%d")}.html" style="text-decoration:none; padding:10px 20px; background-color:#2C3E50; color:white; border-radius:5px; font-weight:bold;">📥 명세서 종합 리포트 다운로드 (HTML)</a>'
        st.markdown(href, unsafe_allow_html=True)
