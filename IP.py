from flask import Flask, request, render_template, redirect, jsonify, send_from_directory
import datetime
import urllib.parse
import threading
import time
import secrets
import string
import os
from dotenv import load_dotenv

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)

DOMAIN = os.getenv("DOMAIN", "https://localhost:5000")
TOKEN_LENGTH = 16
LINK_PATH_PREFIX = "/s/"
TOKEN_EXPIRE_SECONDS = 3600
CLEANUP_INTERVAL = 300

app = Flask(__name__)

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600
app.config['PRESERVE_CONTEXT_ON_EXCEPTION'] = False
app.config['JSON_SORT_KEYS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

TOKEN_TO_RECORD = {}
token_lock = threading.Lock()
is_service_running = False

def generate_unique_token(length=16):
    chars = string.ascii_lowercase + string.ascii_uppercase + string.digits + "_-"
    while True:
        token = ''.join(secrets.choice(chars) for _ in range(length))
        
        if _is_valid_token(token):
            with token_lock:
                if token not in TOKEN_TO_RECORD or TOKEN_TO_RECORD.get(token, {}).get("ip"):
                    return token

def _is_valid_token(token):
    has_lower = False
    has_upper = False
    for c in token:
        if c.islower():
            has_lower = True
        elif c.isupper():
            has_upper = True
        if has_lower and has_upper:
            break
    if not (has_lower and has_upper):
        return False
    
    for i in range(len(token) - 2):
        if token[i] == token[i+1] and token[i+1] == token[i+2]:
            return False
        if token[i] != token[i+1]:
            continue
    
    for i in range(len(token) - 2):
        c1, c2, c3 = ord(token[i]), ord(token[i+1]), ord(token[i+2])
        is_ascending = (c2 - c1 == 1) and (c3 - c2 == 1)
        is_descending = (c1 - c2 == 1) and (c2 - c3 == 1)
        if is_ascending or is_descending:
            return False
        if abs(c2 - c1) > 1:
            continue
    
    return True

def clean_expired_tokens():
    global TOKEN_TO_RECORD, is_service_running
    
    while is_service_running:
        try:
            if not TOKEN_TO_RECORD:
                time.sleep(CLEANUP_INTERVAL * 2)
                continue
            
            current_time = datetime.datetime.now()
            expired_tokens = []
            
            with token_lock:
                for token, record in TOKEN_TO_RECORD.items():
                    create_time_str = record.get("create_time")
                    if not create_time_str:
                        expired_tokens.append(token)
                        continue
                    try:
                        create_time = datetime.datetime.strptime(create_time_str, "%Y-%m-%d %H:%M:%S.%f")
                    except Exception:
                        expired_tokens.append(token)
                        continue
                    time_diff = (current_time - create_time).total_seconds()
                    if time_diff >= TOKEN_EXPIRE_SECONDS and not record.get("ip", ""):
                        expired_tokens.append(token)
            
            if expired_tokens:
                with token_lock:
                    for token in expired_tokens:
                        if token in TOKEN_TO_RECORD:
                            del TOKEN_TO_RECORD[token]
                print(f"定时清理：删除{len(expired_tokens)}个1小时未使用的过期Token")
        
        except Exception as e:
            print(f"定时清理任务异常：{str(e)}")
        
        time.sleep(CLEANUP_INTERVAL)

@app.route("/generate-unique-token")
def generate_unique_token_api():
    try:
        response = jsonify({"success": True, "token": generate_unique_token(TOKEN_LENGTH)})
        response.headers['Cache-Control'] = 'no-cache, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response
    except Exception as e:
        return jsonify({"success": False, "message": f"生成Token失败：{str(e)}"})

@app.route('/static/<path:filename>')
def static_files(filename):
    response = send_from_directory('static', filename)
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

@app.route("/check-token-exists")
def check_token_exists():
    try:
        token = request.args.get("token", "").strip()
        token = urllib.parse.unquote(token) if token else ""
        with token_lock:
            if token in TOKEN_TO_RECORD and not TOKEN_TO_RECORD[token].get("ip", ""):
                return jsonify({"exists": True})
            return jsonify({"exists": False})
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})

@app.route("/")
def index():
    response = render_template("index.html")
    return response

@app.route("/register-token")
def register_token():
    try:
        token = request.args.get("token", "").strip()
        redirect_url = request.args.get("redirectUrl", "").strip()
        token = urllib.parse.unquote(token) if token else ""
        redirect_url = urllib.parse.unquote(redirect_url) if redirect_url else ""
        
        if not token:
            return jsonify({"success": False, "message": "Token无效！"})
        if not redirect_url:
            return jsonify({"success": False, "message": "跳转链接不能为空！"})
        
        with token_lock:
            if token in TOKEN_TO_RECORD and not TOKEN_TO_RECORD[token].get("ip", ""):
                return jsonify({"success": False, "message": "该Token已存在且未被使用，请更换其他Token！"})
            if token in TOKEN_TO_RECORD:
                del TOKEN_TO_RECORD[token]
            
            TOKEN_TO_RECORD[token] = {
                "ip": "",
                "time": "",
                "token": token,
                "redirect_url": redirect_url,
                "create_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            }
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": f"注册失败：{str(e)}"})

@app.route("/s/<token>")
def track(token):
    try:
        request_token = token.strip()
        
        with token_lock:
            if request_token not in TOKEN_TO_RECORD:
                return "<h1 style='text-align:center;margin-top:50px;'>链接失效，无法访问！</h1>", 403
            
            record = TOKEN_TO_RECORD[request_token]
            custom_redirect_url = record["redirect_url"]
            
            if not custom_redirect_url or not custom_redirect_url.startswith(("http://", "https://")):
                custom_redirect_url = "https://www.pingduoduo.com"
            
            if not record.get("ip", ""):
                TOKEN_TO_RECORD[request_token]["ip"] = get_visitor_ip()
                TOKEN_TO_RECORD[request_token]["time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        response = redirect(custom_redirect_url, code=302)
        response.headers['Cache-Control'] = 'no-cache, max-age=0'
        return response
    except Exception as e:
        return f"<h1 style='text-align:center;margin-top:50px;'>服务器异常：{str(e)}</h1>", 500

@app.route("/query-record")
def query_record():
    try:
        query_token = request.args.get("token", "").strip()
        query_token = urllib.parse.unquote(query_token) if query_token else ""
        
        if not query_token:
            return jsonify({"success": False, "message": "Token不能为空！"})
        
        with token_lock:
            if query_token not in TOKEN_TO_RECORD:
                return jsonify({"success": False, "message": "该Token未注册或已过期销毁！"})
            
            record = TOKEN_TO_RECORD[query_token]
            if record.get("ip", ""):
                del TOKEN_TO_RECORD[query_token]
        
        return jsonify({"success": True, "record": record})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

def get_visitor_ip():
    ip = request.headers.get("X-Real-IP", "").strip()
    if ip and ip.lower() != "unknown" and ip != "127.0.0.1":
        return ip
    
    x_forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if x_forwarded_for:
        valid_ips = [x.strip() for x in x_forwarded_for.split(",") if x.strip() and x.strip() != "127.0.0.1"]
        if valid_ips:
            return valid_ips[0]
    
    return request.remote_addr

def init_service():
    global TOKEN_TO_RECORD, is_service_running
    
    with token_lock:
        TOKEN_TO_RECORD = {}
    print("服务启动初始化：已清空所有残留Token")
    
    is_service_running = True
    cleanup_thread = threading.Thread(target=clean_expired_tokens, daemon=True)
    cleanup_thread.start()
    print("后台定时清理任务已启动：每5分钟清理一次1小时未使用的过期Token")



if __name__ == "__main__":
    init_service()
    
    print("=" * 60)
    print("衍楚 · IP追踪工具服务即将启动")
    print("=" * 60)
    print(f"本地访问地址：http://localhost:5000")
    print(f"公网访问地址：{DOMAIN}（已在核心常量中配置）")
    print(r"启动隧道：http://localhost:9200")
    print("=" * 60)
    print("关闭窗口则服务停止，未使用Token1小时后自动销毁")
    print("=" * 60 + "\n")

    from waitress import serve
    try:
        serve(
            app,
            host="0.0.0.0",
            port=5000,
            threads=20,
            connection_limit=1000,
            channel_timeout=30,
            outbuf_overflow=524288
        )
    finally:
        is_service_running = False
        print("服务已停止，后台定时清理任务已退出")
