import os
import re
import time
import asyncio
import streamlit as st
import yt_dlp
import edge_tts
from google import genai

# Cấu hình giao diện chuẩn Điện Thoại & Máy Tính
st.set_page_config(page_title="Phụ Đề, Thuyết Minh & Học Từ Vựng AI", page_icon="🎧", layout="centered")

st.title("🎧 Trích Xuất Phụ Đề, Giọng Đọc & Từ Vựng")
st.caption("Dán link FB, YouTube, Instagram -> Tự động đổi Model & Key khi hết lượt miễn phí")

# Khởi tạo bộ nhớ tạm (Session State)
if "subtitle_result" not in st.session_state:
    st.session_state.subtitle_result = None
if "vocab_result" not in st.session_state:
    st.session_state.vocab_result = None
if "voice_script" not in st.session_state:
    st.session_state.voice_script = None
if "video_title" not in st.session_state:
    st.session_state.video_title = ""
if "audio_bytes" not in st.session_state:
    st.session_state.audio_bytes = None

# Lấy danh sách API Key (Hỗ trợ nhập nhiều Key cách nhau bằng dấu phẩy để nhân số lượt miễn phí)
raw_keys = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
if not raw_keys:
    raw_keys = st.text_input("🔑 Nhập Gemini API Key (Có thể dán nhiều Key cách nhau bằng dấu phẩy):", type="password")

api_keys_list = [k.strip() for k in raw_keys.split(",") if k.strip()]

# Ô dán link
video_url = st.text_input("🔗 Dán link Facebook / YouTube / Instagram vào đây:", placeholder="https://www.facebook.com/share/v/...")

# Tùy chọn cấu hình Phụ đề & Giọng đọc
col1, col2, col3 = st.columns(3)
with col1:
    output_format = st.selectbox(
        "📄 Kiểu phụ đề:",
        [
            "Bản chi tiết -> Dán NotebookLM",
            "Phụ đề kèm thời gian [Phút:Giây]",
            "Chuẩn file .SRT",
            "Văn bản thuần (Đoạn văn)"
        ]
    )
with col2:
    translate_opt = st.selectbox(
        "🌐 Ngôn ngữ chữ:",
        [
            "Song ngữ (Gốc + Việt)",
            "Chỉ xuất tiếng Việt",
            "Giữ nguyên ngôn ngữ gốc"
        ]
    )
with col3:
    voice_choice = st.selectbox(
        "🗣️ Giọng đọc Tiếng Việt:",
        [
            "Nữ - Hoài My (Truyền cảm)",
            "Nam - Nam Minh (Trầm ấm)"
        ]
    )

# THANH CHỈNH TỐC ĐỘ ĐỌC
speed_col1, speed_col2 = st.columns([2, 1])
with speed_col1:
    speed_multiplier = st.slider(
        "⚡ Thanh trượt tốc độ đọc (0.75x -> 2.0x):",
        min_value=0.75,
        max_value=2.0,
        value=1.25,
        step=0.05,
        format="%.2fx"
    )
with speed_col2:
    extract_vocab = st.checkbox("📚 Trích xuất Từ vựng tiếng Anh + IPA", value=True)

rate_percent = int(round((speed_multiplier - 1.0) * 100))
rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

def download_media(url):
    output_file = "temp_media.mp4"
    if os.path.exists(output_file):
        os.remove(output_file)
        
    ydl_opts = {
        'format': 'worst[ext=mp4]/best[height<=480]/best',
        'outtmpl': output_file,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get('title', 'Video_Subtitle')
        platform = info.get('extractor_key', 'Social Media')
    return output_file, title, platform

def analyze_video_all_in_one(file_path, title, platform, url, fmt, lang, include_vocab, status_box):
    vocab_instruction = ""
    if include_vocab:
        vocab_instruction = """
        PHẦN GIỮA `===TACH_TU_VUNG===` VÀ `===TACH_PHAN_DOC===`:
        Trích xuất 5 - 10 từ vựng, cụm động từ (Phrasal Verbs), thành ngữ (Idioms) hoặc cấu trúc tiếng Anh hay nhất xuất hiện trong lời nói hoặc chữ trên màn hình của video (Nếu video hoàn toàn không có tiếng Anh, hãy dịch các từ khóa quan trọng nhất của video sang tiếng Anh).
        Trình bày dưới dạng Bảng Markdown rõ ràng gồm các cột:
        | Từ vựng / Cụm từ | Loại từ | Phiên âm IPA | Nghĩa tiếng Việt (Theo ngữ cảnh) | Câu ví dụ trong video |
        Sau bảng, giải thích ngắn gọn cách phát âm hoặc lưu ý nối âm (nếu có) của 2-3 từ khó nhất.
        """
    else:
        vocab_instruction = """
        PHẦN GIỮA `===TACH_TU_VUNG===` VÀ `===TACH_PHAN_DOC===`:
        Ghi ngắn gọn: "Không bật chế độ trích xuất từ vựng."
        """

    prompt = f"""
    Bạn là hệ thống trích xuất phụ đề, giảng viên tiếng Anh IPA và biên tập viên thuyết minh chuyên nghiệp.
    Thông tin nguồn: Nền tảng {platform} | Tiêu đề: {title} | Link: {url}
    
    YÊU CẦU ĐỊNH DẠNG CHỮ: {fmt}
    YÊU CẦU NGÔN NGỮ: {lang}
    
    Hãy trả về kết quả được chia làm 3 phần ngăn cách nhau chính xác bởi 2 cụm từ khóa `===TACH_TU_VUNG===` và `===TACH_PHAN_DOC===`:
    
    PHẦN 1 (TRƯỚC `===TACH_TU_VUNG===`):
    Trình bày bản phụ đề đầy đủ (quét cả lời thoại âm thanh và chữ chạy trên màn hình Hardsub) theo đúng định dạng "{fmt}" và ngôn ngữ "{lang}". Nếu là bản chi tiết cho NotebookLM, hãy gồm đủ: Phụ đề chi tiết, Mô tả hình ảnh/hành động, và Giải thích ý nghĩa ẩn dụ.
    
    ===TACH_TU_VUNG===
    
    {vocab_instruction}
    
    ===TACH_PHAN_DOC===
    
    PHẦN 3 (SAU `===TACH_PHAN_DOC===`):
    Viết một kịch bản tiếng Việt trôi chảy, tự nhiên (không chứa mốc thời gian, không chứa ký hiệu đặc biệt như *, #, bảng biểu) để đưa vào máy đọc Text-to-Speech cho người dùng nghe. Nội dung gồm:
    - Mở đầu bằng: "Nội dung lời thoại và chữ trong video như sau:" -> Dịch/đọc toàn bộ lời thoại và chữ xuất hiện trên màn hình sang tiếng Việt mạch lạc.
    - Tiếp theo đọc: "Tóm tắt ý nghĩa của video này:" -> Giải thích súc tích thông điệp hoặc ẩn ý của video.
    """
    
    # Danh sách các Model có quỹ lượt miễn phí (Quota) tách biệt nhau
    models_to_try = [
        "gemini-3.8-flash",
        "gemini-3.8-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
        "gemini-flash-latest",
        "gemini-flash-lite-latest",
        "gemini-3.1-pro-preview"
    ]
    
    response = None
    last_error = None
    used_model = ""
    
    # Xoay vòng qua từng API Key và từng Model
    for key_idx, current_key in enumerate(api_keys_list):
        client = genai.Client(api_key=current_key)
        try:
            uploaded_file = client.files.upload(file=file_path)
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)
        except Exception as e:
            last_error = e
            continue
            
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[uploaded_file, prompt]
                )
                used_model = f"{model_name} (Key #{key_idx + 1})"
                break
            except Exception as e:
                err_str = str(e)
                last_error = e
                # Nếu hết lượt trong ngày (429 RESOURCE_EXHAUSTED) hoặc không tìm thấy (404), đổi ngay sang model kế tiếp!
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    status_box.write(f"⚡ Model `{model_name}` (Key #{key_idx+1}) đã hết 20 lượt/ngày, đang tự động đổi sang Model khác...")
                    continue
                elif "404" in err_str or "NOT_FOUND" in err_str:
                    continue
                elif "503" in err_str or "UNAVAILABLE" in err_str:
                    status_box.write(f"⏳ Máy chủ `{model_name}` đang bận, đang chuyển sang luồng dự phòng...")
                    time.sleep(2)
                    continue
                else:
                    continue
                    
        # Dọn file trên cloud của key hiện tại
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
            
        if response is not None:
            status_box.write(f"✅ Đã xử lý thành công bằng: **{used_model}**")
            break
            
    if response is None:
        raise last_error
    
    full_text = response.text
    subtitle_part = full_text
    vocab_part = ""
    tts_part = ""

    if "===TACH_TU_VUNG===" in full_text and "===TACH_PHAN_DOC===" in full_text:
        p1, rest = full_text.split("===TACH_TU_VUNG===", 1)
        p2, p3 = rest.split("===TACH_PHAN_DOC===", 1)
        subtitle_part = p1.strip()
        vocab_part = p2.strip()
        tts_part = p3.strip()
    elif "===TACH_PHAN_DOC===" in full_text:
        p1, p3 = full_text.split("===TACH_PHAN_DOC===", 1)
        subtitle_part = p1.strip()
        tts_part = p3.strip()
    else:
        tts_part = re.sub(r'\[?\d{1,2}:\d{2}(?::\d{2})?(?:,\d{3})?\]?', '', full_text)
        tts_part = re.sub(r'[*#_>|`~-]', '', tts_part)
        
    return subtitle_part, vocab_part, tts_part

async def generate_vietnamese_audio(text_to_read, voice_code, speed_rate, output_audio_path):
    communicate = edge_tts.Communicate(text_to_read, voice_code, rate=speed_rate)
    await communicate.save(output_audio_path)

def create_audio_bytes(script_text, selected_voice, speed_rate):
    voice_id = "vi-VN-HoaiMyNeural" if "Hoài My" in selected_voice else "vi-VN-NamMinhNeural"
    audio_file = "vietnamese_tts.mp3"
    asyncio.run(generate_vietnamese_audio(script_text, voice_id, speed_rate, audio_file))
    with open(audio_file, "rb") as f:
        return f.read()

# NÚT BẤM CHÍNH
if st.button("🚀 TRÍCH XUẤT PHỤ ĐỀ, TỪ VỰNG & TẠO GIỌNG ĐỌC", use_container_width=True, type="primary"):
    if not api_keys_list:
        st.error("⚠️ Vui lòng nhập ít nhất 1 Gemini API Key!")
    elif not video_url.strip():
        st.warning("⚠️ Bạn chưa dán link video!")
    else:
        try:
            with st.status("Đang xử lý video, lọc từ vựng & tạo giọng đọc...", expanded=True) as status:
                st.write("📥 1. Đang tải dữ liệu từ link của bạn...")
                media_path, v_title, platform_name = download_media(video_url)
                
                st.write(f"🧠 2. Đang tách phụ đề, đọc chữ trên màn hình & lọc từ vựng IPA...")
                sub_res, voc_res, v_script = analyze_video_all_in_one(
                    media_path, v_title, platform_name, video_url, output_format, translate_opt, extract_vocab, status
                )
                
                if os.path.exists(media_path):
                    os.remove(media_path)
                
                st.write(f"🎙️ 3. Đang tạo giọng đọc Tiếng Việt ở tốc độ {speed_multiplier}x ({rate_str})...")
                aud_bytes = create_audio_bytes(v_script, voice_choice, rate_str)
                
                st.session_state.subtitle_result = sub_res
                st.session_state.vocab_result = voc_res
                st.session_state.voice_script = v_script
                st.session_state.video_title = v_title
                st.session_state.audio_bytes = aud_bytes
                    
                status.update(label="✅ Hoàn tất! Mời bạn nghe và xem kết quả bên dưới.", state="complete", expanded=False)
                
        except Exception as e:
            st.error(f"❌ Toàn bộ các Model trong Key hiện tại đều đã hết lượt miễn phí hôm nay. Bạn hãy tạo thêm 1 API Key ở Project mới và dán thêm vào Secrets nhé! Chi tiết: {e}")

# HIỂN THỊ KẾT QUẢ
if st.session_state.subtitle_result:
    st.divider()
    
    col_audio_header, col_regen_btn = st.columns([2, 1])
    with col_audio_header:
        st.subheader(f"🔊 Nghe Thuyết Minh ({speed_multiplier}x)")
    with col_regen_btn:
        if st.button("🔄 Áp dụng tốc độ mới", use_container_width=True):
            with st.spinner(f"Đang chuyển sang tốc độ {speed_multiplier}x..."):
                st.session_state.audio_bytes = create_audio_bytes(
                    st.session_state.voice_script, voice_choice, rate_str
                )
    
    st.audio(st.session_state.audio_bytes, format="audio/mp3")
    
    with st.expander("👀 Xem kịch bản lời đọc tiếng Việt"):
        st.write(st.session_state.voice_script)
        
    if extract_vocab and st.session_state.vocab_result:
        st.subheader("📚 Từ Vựng & Cụm Từ Tiếng Anh Đắt Giá (Kèm IPA)")
        st.markdown(st.session_state.vocab_result)
    
    st.subheader(f"📝 Bản Phụ Đề & Ghi Chú (Copy vào NotebookLM): {st.session_state.video_title}")
    combined_notebooklm_text = st.session_state.subtitle_result
    if extract_vocab and st.session_state.vocab_result and ".SRT" not in output_format:
        combined_notebooklm_text += f"\n\n---\n### TỪ VỰNG TIẾNG ANH TRONG VIDEO\n{st.session_state.vocab_result}"
        
    st.code(combined_notebooklm_text, language="markdown")
    
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        file_ext = "srt" if ".SRT" in output_format else "txt"
        st.download_button(
            label=f"💾 Tải Phụ đề (.{file_ext})",
            data=combined_notebooklm_text.encode("utf-8"),
            file_name=f"subtitle_vocab.{file_ext}",
            mime="text/plain",
            use_container_width=True
        )
    with btn_col2:
        st.download_button(
            label=f"🎵 Tải MP3 ({speed_multiplier}x)",
            data=st.session_state.audio_bytes,
            file_name=f"thuyet_minh_{speed_multiplier}x.mp3",
            mime="audio/mp3",
            use_container_width=True
        )
    with btn_col3:
        st.link_button(
            "👉 Mở NotebookLM", 
            "https://notebooklm.google.com/", 
            use_container_width=True
        )
