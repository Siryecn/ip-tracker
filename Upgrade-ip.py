from playwright.sync_api import sync_playwright
import os
import re
import time
import subprocess
from dotenv import load_dotenv

load_dotenv()
CPOLAR_ACCOUNT = os.getenv("CPOLAR_ACCOUNT", "")
CPOLAR_PASSWORD = os.getenv("CPOLAR_PASSWORD", "")
TARGET_FILE_PATH = os.getenv("TARGET_FILE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "IP.py"))
CPOLAR_LOCAL_PAGE = "http://localhost:9200"
DOMAIN_PATTERN_PREFIX = "https://"
HEADLESS_MODE = True

def auto_login_cpolar(page):
    try:
        print("检测当前登录状态...")
        email_input = page.wait_for_selector(
            'input[type="email"], input[placeholder="Email"]',
            timeout=10000
        )
        if email_input:
            print("进入Cpolar登录页面，开始自动填写账号密码...")
            email_input.click()
            email_input.fill(CPOLAR_ACCOUNT)
            print(f"邮箱填写完成：{CPOLAR_ACCOUNT}")
            password_input = page.wait_for_selector(
                'input[type="password"]',
                timeout=5000
            )
            password_input.click()
            password_input.fill(CPOLAR_PASSWORD)
            print("密码填写完成（隐藏显示，保护隐私）")
            login_button = page.wait_for_selector(
                'button:has-text("登录")',
                timeout=5000
            )
            page.wait_for_timeout(500)
            login_button.click()
            print("已点击登录按钮，等待跳转至Cpolar管理后台...")
            page.wait_for_selector('text="状态"', timeout=20000)
            print("自动登录成功！已进入Cpolar本地管理后台")
        else:
            print("检测到已处于登录状态，无需重复登录")
    except Exception as e:
        raise Exception(f"自动登录流程失败：{str(e)}")

def crawl_cpolar_domain():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS_MODE)
            page = browser.new_page()
            print("=" * 50)
            print(f"开始访问Cpolar本地管理页面：{CPOLAR_LOCAL_PAGE}")
            page.goto(CPOLAR_LOCAL_PAGE)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            auto_login_cpolar(page)
            print("定位并点击左侧导航「状态」菜单...")
            status_menu = page.wait_for_selector('text="状态"', timeout=10000)
            status_menu.click()
            page.wait_for_timeout(1000)
            print("定位并点击「在线隧道列表」子选项...")
            online_tunnel = page.wait_for_selector('text="在线隧道列表"', timeout=10000)
            online_tunnel.click()
            page.wait_for_timeout(1500)
            print("提取有效HTTPS公网域名（仅选取本地地址为localhost:5000的HTTPS隧道）...")
            page.wait_for_selector("table", timeout=10000)
            public_url = page.evaluate(
                """() => {
                    const text = el => (el.innerText || el.textContent || '').trim();
                    const pick = (sel, fallback) => {
                        const nodes = document.querySelectorAll(sel);
                        return nodes.length ? Array.from(nodes) : Array.from(document.querySelectorAll(fallback));
                    };
                    const headers = pick('.el-table__header-wrapper thead th', 'table thead th').map(text);
                    const colIndex = keywords => headers.findIndex(h => keywords.some(k => h.includes(k)));
                    const pubIdx = colIndex(['公网地址', '公共地址', '公网']);
                    const protoIdx = colIndex(['协议']);
                    const localIdx = colIndex(['本地地址', '本地']);
                    if (pubIdx < 0 || protoIdx < 0 || localIdx < 0) return '';
                    const rows = pick('.el-table__body-wrapper tbody tr', 'table tbody tr');
                    for (const row of rows) {
                        const cells = Array.from(row.querySelectorAll('td')).map(text);
                        const proto = (cells[protoIdx] || '').trim();
                        const local = (cells[localIdx] || '').trim();
                        const pub = cells[pubIdx] || '';
                        const localOk = /:\\/\\/(localhost|127\\.0\\.0\\.1):5000$/.test(local)
                            || /^(localhost|127\\.0\\.0\\.1):5000$/.test(local);
                        const match = pub.match(/https:\\/\\/[^\\s]+/);
                        if (/^https$/i.test(proto) && localOk && match) {
                            return match[0];
                        }
                    }
                    return '';
                }"""
            )
            if not public_url or not public_url.startswith(DOMAIN_PATTERN_PREFIX):
                raise Exception("未找到协议为HTTPS且本地地址为localhost:5000的隧道公网域名，无法继续更新")
            print(f"公网域名提取成功：{public_url}")
            browser.close()
            return public_url
    except Exception as e:
        raise Exception(f"域名爬取流程失败：{str(e)}")

def validate_domain(domain):
    if not domain:
        return False, "域名为空，验证失败"
    if not domain.startswith(DOMAIN_PATTERN_PREFIX):
        return False, f"域名格式错误，必须以「{DOMAIN_PATTERN_PREFIX}」开头"
    if "cpolar" not in domain.lower():
        print("温馨提示：提取的域名不包含「cpolar」，请确认隧道配置是否正常")
    return True, "域名格式合法，验证通过"

def modify_env_file(target_file, new_domain):
    try:
        env_file = os.path.join(os.path.dirname(os.path.abspath(target_file)), ".env")
        if not os.path.exists(env_file):
            raise FileNotFoundError(f".env 文件不存在：{env_file}，无法进行更新")
        with open(env_file, "r", encoding="utf-8") as f:
            file_content = f.read()
        domain_pattern = r'^DOMAIN=.*$'
        new_domain_line = f'DOMAIN={new_domain}'
        updated_content = re.sub(domain_pattern, new_domain_line, file_content, flags=re.MULTILINE)
        
        if new_domain_line not in updated_content:
            raise Exception("未在 .env 中找到可匹配的 DOMAIN 配置行，更新失败")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f".env 文件更新成功，DOMAIN 已替换为：{new_domain}")
    except Exception as e:
        raise Exception(f".env 文件更新失败：{str(e)}")

def stop_existing_ip_service():
    print("检测5000端口占用，关闭旧IP.py服务（含其CMD父窗口）...")
    ps_script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$owningPids = Get-NetTCPConnection -LocalPort 5000 -State Listen | "
        "Select-Object -ExpandProperty OwningProcess -Unique;"
        "foreach ($procId in $owningPids) {"
        "  $proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$procId\";"
        "  if ($proc -and $proc.Name -eq 'python.exe') {"
        "    $parent = Get-CimInstance Win32_Process -Filter \"ProcessId=$($proc.ParentProcessId)\";"
        "    if ($parent -and $parent.Name -eq 'cmd.exe') { taskkill /PID $proc.ParentProcessId /T /F | Out-Null }"
        "    else { taskkill /PID $procId /T /F | Out-Null }"
        "  }"
        "}"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True, text=True, timeout=60
    )
    for _ in range(30):
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue).Count"],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip() in ("0", ""):
            print("旧服务已关闭，5000端口已释放")
            return
        time.sleep(1)
    raise Exception("等待5000端口释放超时（30秒），旧服务可能未完全退出")

def auto_open_cmd_and_run_ip_py():
    try:
        ip_py_full_path = os.path.abspath(TARGET_FILE_PATH)
        cmd_command = f'start "IP.py运行窗口" cmd /k "python "{ip_py_full_path}""'
        os.system(cmd_command)
        print(f"已用Windows原生命令启动IP.py，新CMD窗口已弹出并保留")
        print(f"IP.py运行路径：{ip_py_full_path}")
    except Exception as e:
        raise Exception(f"IP.py启动失败：{str(e)}")

def main():
    print("=" * 60)
    print("Cpolar 自动登录+域名提取+IP.py+自动启动工具")
    print("=" * 60)
    
    try:
        new_cpolar_domain = crawl_cpolar_domain()
        
        is_valid, validate_msg = validate_domain(new_cpolar_domain)
        if not is_valid:
            print(f"域名验证失败：{validate_msg}")
            return
        print(f"域名验证通过：{validate_msg}")
        print("\n" + "-" * 50)
        print(f"自动更新.env域名配置，无需手动干预...")
        modify_env_file(TARGET_FILE_PATH, new_cpolar_domain)
        print("\n" + "-" * 50)
        stop_existing_ip_service()
        auto_open_cmd_and_run_ip_py()
        print("\n" + "=" * 60)
        print("所有流程全自动执行完成！")
        print("最终结果：.env已更新，IP.py已启动，仅保留IP.py运行窗口")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n脚本执行异常终止：{str(e)}")

if __name__ == "__main__":
    main()
