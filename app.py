
from flask import Flask, render_template, request, jsonify, url_for
from flask_cors import CORS
import yt_dlp
import os
import uuid
import logging
import time
import random
import subprocess
import sys

# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = 'static/downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


def try_download_with_opts(url, ydl_opts):
    """Try to download with given ydl_opts. Returns local filepath on success."""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        return filename


@app.route('/api/download', methods=['POST'])
def api_download():
    """
    Expects JSON: { "url": "<youtube url>", "format": "mp3|mp4" }
    Returns JSON: { status: "success", download_url: "<public-url>" } or error.
    """
    data = request.get_json() or {}
    url = data.get("url")
    format_type = data.get("format", "mp4")
    if not url:
        return jsonify({"status": "error", "message": "URL is required"}), 400

    # unique id so multiple downloads don't collide
    video_id = str(uuid.uuid4())
    out_template = os.path.join(DOWNLOAD_FOLDER, f"{video_id}.%(ext)s")

    # Enhanced user agents with mobile variants
    user_agents = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Android 13; Mobile; rv:109.0) Gecko/111.0 Firefox/111.0",
        "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]

    # Random delay between requests
    time.sleep(random.uniform(2, 5))

    # Configure download options with multiple bypass strategies
    base_headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0"
    }
    
    if format_type == "mp3":
        # Audio download strategies
        opts_list = [
            # Strategy 1: Mobile bypass with Invidious
            {
                "outtmpl": out_template,
                "format": "bestaudio/best",
                "noplaylist": True,
                "extractor_args": {
                    "youtube": {
                        "skip": ["hls", "dash"],
                        "player_skip": ["config"]
                    }
                },
                "http_headers": {
                    **base_headers,
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                },
                "socket_timeout": 30,
                "no_warnings": True,
                "quiet": True,
                "extract_flat": False,
                "ignoreerrors": True,
            },
            # Strategy 2: Alternative extractor
            {
                "outtmpl": out_template,
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "noplaylist": True,
                "force_generic_extractor": True,
                "http_headers": base_headers,
                "socket_timeout": 45,
                "no_warnings": True,
                "quiet": True,
                "ignoreerrors": True,
            },
            # Strategy 3: Simple fallback
            {
                "outtmpl": out_template,
                "format": "worst/bestaudio/best",
                "noplaylist": True,
                "http_headers": {
                    "User-Agent": "yt-dlp/2023.01.06"
                },
                "socket_timeout": 60,
                "no_warnings": True,
                "quiet": True,
                "ignoreerrors": True,
            }
        ]
    else:
        # Video download strategies  
        opts_list = [
            # Strategy 1: Mobile bypass
            {
                "outtmpl": out_template,
                "format": "best[height<=720]/best[height<=480]/best",
                "noplaylist": True,
                "extractor_args": {
                    "youtube": {
                        "skip": ["hls", "dash"],
                        "player_skip": ["config"]
                    }
                },
                "http_headers": {
                    **base_headers,
                    "User-Agent": "Mozilla/5.0 (Android 13; Mobile; rv:109.0) Gecko/111.0 Firefox/111.0"
                },
                "socket_timeout": 30,
                "no_warnings": True,
                "quiet": True,
                "extract_flat": False,
                "ignoreerrors": True,
            },
            # Strategy 2: Generic extractor bypass
            {
                "outtmpl": out_template,
                "format": "best[ext=mp4]/best",
                "noplaylist": True,
                "force_generic_extractor": True,
                "http_headers": base_headers,
                "socket_timeout": 45,
                "no_warnings": True,
                "quiet": True,
                "ignoreerrors": True,
            },
            # Strategy 3: Low quality fallback
            {
                "outtmpl": out_template,
                "format": "worst/best",
                "noplaylist": True,
                "http_headers": {
                    "User-Agent": "yt-dlp/2023.01.06"
                },
                "socket_timeout": 60,
                "no_warnings": True,
                "quiet": True,
                "ignoreerrors": True,
            }
        ]

    last_error = None
    strategy_names = ["Mobile Bypass", "Generic Extractor", "Simple Fallback"]
    
    for idx, opts in enumerate(opts_list, start=1):
        try:
            strategy_name = strategy_names[idx-1] if idx <= len(strategy_names) else f"Strategy {idx}"
            logger.info("Attempt %d (%s): trying download with format: %s", idx, strategy_name, opts.get('format', 'unknown'))
            
            # Progressive delay between attempts
            if idx > 1:
                delay = random.uniform(3, 8) * idx  # Increasing delay
                time.sleep(delay)
            
            filename = try_download_with_opts(url, opts)
            if not os.path.isfile(filename):
                raise Exception(f"Download completed but file not found: {filename}")

            file_basename = os.path.basename(filename)
            download_url = url_for('static', filename=f"downloads/{file_basename}", _external=True)
            logger.info("✅ Download successful with %s (attempt %d)", strategy_name, idx)
            return jsonify({
                "status": "success", 
                "download_url": download_url,
                "strategy_used": strategy_name
            }), 200

        except Exception as e:
            error_msg = str(e)
            logger.warning("❌ %s failed: %s", strategy_name, error_msg)
            last_error = error_msg
            
            # Continue to next strategy regardless of error type
            continue

    # If all strategies fail, return success with a placeholder
    # This ensures user always gets a response
    placeholder_file = os.path.join(DOWNLOAD_FOLDER, f"{video_id}_placeholder.txt")
    with open(placeholder_file, 'w') as f:
        f.write(f"Download temporarily unavailable for: {url}\nTry again later or use a different video.")
    
    file_basename = os.path.basename(placeholder_file)
    download_url = url_for('static', filename=f"downloads/{file_basename}", _external=True)
    
    return jsonify({
        "status": "partial_success", 
        "download_url": download_url,
        "message": "Video download kar nahi paya, lekin placeholder file bana diya hai. Thodi der baad try karo.",
        "details": last_error
    }), 200


@app.route('/download', methods=['POST'])
def download_form():
    url = request.form.get('url')
    format_type = request.form.get('format', 'mp4')
    if not url:
        return "Error: URL is required", 400

    response = app.test_client().post('/api/download', json={"url": url, "format": format_type})
    return response.get_data(as_text=True), response.status_code, {'Content-Type': 'application/json'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
