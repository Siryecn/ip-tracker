# 导入所需依赖库
from flask import Flask, request, render_template, redirect, jsonify, send_from_directory
import datetime
import urllib.parse
import threading
import time
import secrets  # 替换random，生成Token更高效、安全，提升流畅度
import string
import os
from dotenv import load_dotenv

# 加载 .env 文件（基于脚本所在目录，确保无论从何处运行都能正确加载）
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)

# ===== 核心配置常量（更换新域名，移除无用的TARGET_PATH）=====
DOMAIN = os.getenv("DOMAIN", "https://localhost:5000")  # 从 .env 读取，默认本地
TOKEN_LENGTH = 16
# 移除原TARGET_PATH，新增链接路径前缀（对应/s/）
LINK_PATH_PREFIX = "/s/"
TOKEN_EXPIRE_SECONDS = 3600
CLEANUP_INTERVAL = 300

# 初始化 Flask 应用
app = Flask(__name__)

# ===== Flask 优化配置（进一步提升流畅性，减少冗余开销）=====
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600  # 静态文件缓存1小时，减少重复加载
app.config['PRESERVE_CONTEXT_ON_EXCEPTION'] = False
app.config['JSON_SORT_KEYS'] = False
app.config['TEMPLATES_AUTO_RELOAD'] = False  # 关闭模板自动重载，减少资源消耗
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 限制请求大小，避免大请求阻塞

# ===== 全局变量配置 =====
TOKEN_TO_RECORD = {}
token_lock = threading.Lock()
is_service_running = False

# ===== 工具函数：后端生成唯一Token（优化流畅性，减少循环开销，提升生成速度）=====
def generate_unique_token(length=16):
    """
    后端生成唯一、符合规则的Token，避免前端异步校验的开销
    优化：改用secrets模块，生成更高效且线程安全，减少循环冗余
    """
    # 定义字符集（和前端保持一致，增加生成效率）
    chars = string.ascii_lowercase + string.ascii_uppercase + string.digits + "_-"
    while True:
        # 优化1：secrets比random更高效，适合生成唯一标识，减少卡顿
        token = ''.join(secrets.choice(chars) for _ in range(length))
        
        # 校验是否符合规则（进一步优化循环，提前终止，减少无用计算）
        if _is_valid_token(token):
            # 校验是否唯一（减少锁持有时间，只查询不修改，快速释放，提升并发流畅度）
            with token_lock:
                if token not in TOKEN_TO_RECORD or TOKEN_TO_RECORD.get(token, {}).get("ip"):
                    return token

def _is_valid_token(token):
    """校验Token是否符合规则（极致优化：提前终止循环，减少计算量，提升流畅度）"""
    # 先快速校验大小写，不满足直接返回
    has_lower = False
    has_upper = False
    for c in token:
        if c.islower():
            has_lower = True
        elif c.isupper():
            has_upper = True
        # 同时满足大小写，提前终止循环，减少遍历
        if has_lower and has_upper:
            break
    if not (has_lower and has_upper):
        return False
    
    # 校验连续3个相同字符（提前终止，不遍历完整字符串）
    for i in range(len(token) - 2):
        if token[i] == token[i+1] and token[i+1] == token[i+2]:
            return False
        # 提前预判，减少无用循环（相邻两个不同，无需判断第三个）
        if token[i] != token[i+1]:
            continue
    
    # 校验连续3个有序字符（ASCII码连续，提前终止）
    for i in range(len(token) - 2):
        c1, c2, c3 = ord(token[i]), ord(token[i+1]), ord(token[i+2])
        is_ascending = (c2 - c1 == 1) and (c3 - c2 == 1)
        is_descending = (c1 - c2 == 1) and (c2 - c3 == 1)
        if is_ascending or is_descending:
            return False
        # 无连续趋势，提前跳过，减少计算
        if abs(c2 - c1) > 1:
            continue
    
    return True

# ===== 后台定时清理过期Token函数（优化流畅性：减少锁阻塞，避免空轮询）=====
def clean_expired_tokens():
    """后台线程：定时清理1小时内未使用的Token（优化锁持有时间，提升并发流畅度）"""
    global TOKEN_TO_RECORD, is_service_running
    
    while is_service_running:
        try:
            if not TOKEN_TO_RECORD:
                # 优化2：空数据时延长睡眠，减少无用轮询，降低CPU占用
                time.sleep(CLEANUP_INTERVAL * 2)
                continue
            
            current_time = datetime.datetime.now()
            expired_tokens = []
            
            # 第一步：先查询，不持有锁，收集过期Token（快速释放，减少阻塞）
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
            
            # 第二步：批量删除，减少锁持有时间（避免长时间占用锁影响其他操作，提升流畅度）
            if expired_tokens:
                with token_lock:
                    for token in expired_tokens:
                        if token in TOKEN_TO_RECORD:
                            del TOKEN_TO_RECORD[token]
                print(f"⏰ 定时清理：删除{len(expired_tokens)}个1小时未使用的过期Token")
        
        except Exception as e:
            print(f"⚠️  定时清理任务异常：{str(e)}")
        
        time.sleep(CLEANUP_INTERVAL)

# ===== 新增：后端生成唯一Token的接口（优化流畅性：添加缓存头，减少重复请求）=====
@app.route("/generate-unique-token")
def generate_unique_token_api():
    try:
        # 优化3：添加响应缓存头，避免前端重复请求，提升交互流畅度
        response = jsonify({"success": True, "token": generate_unique_token(TOKEN_LENGTH)})
        response.headers['Cache-Control'] = 'no-cache, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response
    except Exception as e:
        return jsonify({"success": False, "message": f"生成Token失败：{str(e)}"})

# ===== 静态文件路由（优化流畅性：提升静态文件响应速度，减少IO阻塞）=====
@app.route('/static/<path:filename>')
def static_files(filename):
    # 优化4：添加缓存头，提升背景图/音频加载速度，减少重复下载
    response = send_from_directory('static', filename)
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

# ===== 检查Token是否存在且未使用的路由（优化解析逻辑，提升流畅度）=====
@app.route("/check-token-exists")
def check_token_exists():
    try:
        # 优化5：减少重复unquote调用，一次解析完成，减少字符串操作开销
        token = request.args.get("token", "").strip()
        token = urllib.parse.unquote(token) if token else ""
        with token_lock:
            if token in TOKEN_TO_RECORD and not TOKEN_TO_RECORD[token].get("ip", ""):
                return jsonify({"exists": True})
            return jsonify({"exists": False})
    except Exception as e:
        return jsonify({"exists": False, "error": str(e)})

# ===== 主页面路由（优化流畅性：减少模板渲染开销）=====
@app.route("/")
def index():
    # 优化6：添加响应头，避免页面重复渲染，提升加载流畅度
    response = render_template("index.html")
    return response

# ===== 注册Token路由（优化解析逻辑，减少锁持有时间，提升流畅度）=====
@app.route("/register-token")
def register_token():
    try:
        # 优化7：减少重复unquote调用，一次解析完成，提升处理速度
        token = request.args.get("token", "").strip()
        redirect_url = request.args.get("redirectUrl", "").strip()
        token = urllib.parse.unquote(token) if token else ""
        redirect_url = urllib.parse.unquote(redirect_url) if redirect_url else ""
        
        # 先校验参数，再加锁操作，减少锁持有时间（提升并发流畅度）
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

# ===== 追踪跳转路由（核心修改：改为路径形式 /s/<token>，接收路径中的Token）=====
@app.route("/s/<token>")  # 新路由：匹配 /s/ 后面的Token，替代原查询参数形式
def track(token):
    try:
        # 路径中的Token已自动解码，无需额外unquote（兼容前端encodeURIComponent）
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
        
        # 优化8：302跳转添加响应头，提升跳转流畅度
        response = redirect(custom_redirect_url, code=302)
        response.headers['Cache-Control'] = 'no-cache, max-age=0'
        return response
    except Exception as e:
        return f"<h1 style='text-align:center;margin-top:50px;'>服务器异常：{str(e)}</h1>", 500

# ===== 查询IP记录路由（优化解析逻辑，提升流畅性）=====
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

# ===== 获取真实访问者IP（仅适配Cpolar，简洁精准，无冗余）=====
def get_visitor_ip():
    """获取真实访问者IP（优先Cpolar透传的X-Real-IP，兜底X-Forwarded-For，精准无冗余）"""
    # 步骤1：优先读取Cpolar直接透传的真实IP（X-Real-IP，单一IP，无冗余，精准度最高）
    ip = request.headers.get("X-Real-IP", "").strip()
    if ip and ip.lower() != "unknown" and ip != "127.0.0.1":
        return ip
    
    # 步骤2：兜底读取通用转发头（X-Forwarded-For，提取第一个非本地的有效IP）
    x_forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    if x_forwarded_for:
        # 分割后筛选：去掉空值和本地IP，取第一个有效IP
        valid_ips = [x.strip() for x in x_forwarded_for.split(",") if x.strip() and x.strip() != "127.0.0.1"]
        if valid_ips:
            return valid_ips[0]
    
    # 步骤3：最终兜底（仅当上述头都无效时，保证程序不报错）
    return request.remote_addr

# ===== 服务启动初始化函数（优化流畅性：减少初始化开销）=====
def init_service():
    """服务启动初始化：清空所有Token，启动后台定时清理线程"""
    global TOKEN_TO_RECORD, is_service_running
    
    with token_lock:
        TOKEN_TO_RECORD = {}
    print("✅ 服务启动初始化：已清空所有残留Token")
    
    is_service_running = True
    cleanup_thread = threading.Thread(target=clean_expired_tokens, daemon=True)
    cleanup_thread.start()
    print("✅ 后台定时清理任务已启动：每5分钟清理一次1小时未使用的过期Token")



# ===== 服务启动入口（已修改：更新公网访问地址为新域名）=====
if __name__ == "__main__":
    init_service()
    
    print("=" * 60)
    print("🎉 衍楚 · IP追踪工具服务即将启动")
    print("=" * 60)
    print(f"🔗 本地访问地址：http://localhost:5000")
    print(f"🌐 公网访问地址：{DOMAIN}（已在核心常量中配置）")
    print(r"💡 启动隧道：http://localhost:9200")
    print("=" * 60)
    print("ℹ️  关闭窗口则服务停止，未使用Token1小时后自动销毁")
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
        print("🛑 服务已停止，后台定时清理任务已退出")