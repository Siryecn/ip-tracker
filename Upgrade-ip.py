from playwright.sync_api import sync_playwright
import os
import re
from dotenv import load_dotenv

# 加载 .env 文件（当前目录）
load_dotenv()

# ===== 【配置项 - 从 .env 动态加载】 =====
CPOLAR_ACCOUNT = os.getenv("CPOLAR_ACCOUNT", "")  # 从 .env 读取
CPOLAR_PASSWORD = os.getenv("CPOLAR_PASSWORD", "")  # 从 .env 读取

# IP.py 路径：优先使用环境变量，否则使用相对路径（当前脚本所在目录的 IP.py）
TARGET_FILE_PATH = os.getenv("TARGET_FILE_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "IP.py"))

# ===== 固定配置（无需修改） =====
CPOLAR_LOCAL_PAGE = "http://localhost:9200"
DOMAIN_PATTERN_PREFIX = "https://"
HEADLESS_MODE = True  # 保持False，可观察浏览器操作流程（可选改为True隐藏浏览器）

def auto_login_cpolar(page):
    """适配你的Cpolar页面，完成自动登录（兼容旧版Playwright，无新版本依赖）"""
    try:
        print("🔍 检测当前登录状态...")
        # 定位邮箱输入框（匹配你的登录页Email输入框，100%精准）
        email_input = page.wait_for_selector(
            'input[type="email"], input[placeholder="Email"]',
            timeout=10000
        )
        
        if email_input:
            print("✅ 进入Cpolar登录页面，开始自动填写账号密码...")
            # 填写邮箱（自动覆盖输入框原有内容，无需清空）
            email_input.click()
            email_input.fill(CPOLAR_ACCOUNT)
            print(f"📧 邮箱填写完成：{CPOLAR_ACCOUNT}")
            
            # 定位并填写密码输入框
            password_input = page.wait_for_selector(
                'input[type="password"]',
                timeout=5000
            )
            password_input.click()
            password_input.fill(CPOLAR_PASSWORD)
            print("🔒 密码填写完成（隐藏显示，保护隐私）")
            
            # 定位并点击登录按钮（短暂等待确保按钮就绪，兼容旧版Playwright）
            login_button = page.wait_for_selector(
                'button:has-text("登录")',
                timeout=5000
            )
            page.wait_for_timeout(500)  # 等待500毫秒，确保按钮可点击
            login_button.click()
            print("🚀 已点击登录按钮，等待跳转至Cpolar管理后台...")
            
            # 验证登录成功（匹配你页面上的"状态"文本，100%可靠，无无效选择器）
            page.wait_for_selector('text="状态"', timeout=20000)
            print("🎉 自动登录成功！已进入Cpolar本地管理后台")
        else:
            print("🎉 检测到已处于登录状态，无需重复登录")
    
    except Exception as e:
        raise Exception(f"❌ 自动登录流程失败：{str(e)}")

def crawl_cpolar_domain():
    """完整流程：启动浏览器→自动登录→导航菜单→提取HTTPS公网域名"""
    try:
        with sync_playwright() as p:
            # 启动Chromium浏览器（可视化模式，可观察操作；改为headless=True可隐藏浏览器）
            browser = p.chromium.launch(headless=HEADLESS_MODE)
            page = browser.new_page()
            
            # 访问Cpolar 9200端口本地管理页面
            print("=" * 50)
            print(f"📌 开始访问Cpolar本地管理页面：{CPOLAR_LOCAL_PAGE}")
            page.goto(CPOLAR_LOCAL_PAGE)
            page.wait_for_load_state("domcontentloaded", timeout=20000)  # 等待页面核心内容加载
            
            # 执行自动登录流程
            auto_login_cpolar(page)
            
            # 导航：点击左侧"状态"菜单，展开子选项
            print("🔍 定位并点击左侧导航「状态」菜单...")
            status_menu = page.wait_for_selector('text="状态"', timeout=10000)
            status_menu.click()
            page.wait_for_timeout(1000)  # 等待下拉子菜单展开
            
            # 导航：点击"在线隧道列表"，进入域名表格页面
            print("🔍 定位并点击「在线隧道列表」子选项...")
            online_tunnel = page.wait_for_selector('text="在线隧道列表"', timeout=10000)
            online_tunnel.click()
            page.wait_for_timeout(1500)  # 延长等待至1.5秒，确保域名表格完全加载
            
            # 提取HTTPS公网域名（直接从浏览器渲染页面获取，无需解析源码，100%精准）
            print("🔍 提取有效HTTPS公网域名...")
            domain_element = page.wait_for_selector(
                f'td .cell:has-text("{DOMAIN_PATTERN_PREFIX}")',
                timeout=10000
            )
            public_url = domain_element.text_content().strip()
            
            # 验证提取结果是否有效
            if not public_url or not public_url.startswith(DOMAIN_PATTERN_PREFIX):
                raise Exception("提取到的域名为空或格式无效，无法继续更新")
            print(f"🎉 公网域名提取成功：{public_url}")
            
            # 关闭浏览器窗口，无残留
            browser.close()
            
            # 返回提取到的纯净域名
            return public_url
    
    except Exception as e:
        raise Exception(f"❌ 域名爬取流程失败：{str(e)}")

def validate_domain(domain):
    """验证提取的域名格式是否合法有效，避免无效更新"""
    if not domain:
        return False, "域名为空，验证失败"
    if not domain.startswith(DOMAIN_PATTERN_PREFIX):
        return False, f"域名格式错误，必须以「{DOMAIN_PATTERN_PREFIX}」开头"
    if "cpolar" not in domain.lower():
        print("⚠️  温馨提示：提取的域名不包含「cpolar」，请确认隧道配置是否正常")
    return True, "域名格式合法，验证通过"

def modify_env_file(target_file, new_domain):
    """自动更新 .env 文件中的 DOMAIN 常量"""
    try:
        # 获取 .env 文件路径（与脚本同目录）
        env_file = os.path.join(os.path.dirname(os.path.abspath(target_file)), ".env")
        
        # 检查 .env 文件是否存在
        if not os.path.exists(env_file):
            raise FileNotFoundError(f".env 文件不存在：{env_file}，无法进行更新")
        
        # 读取 .env 原有内容
        with open(env_file, "r", encoding="utf-8") as f:
            file_content = f.read()
        
        # 替换 DOMAIN 配置行
        domain_pattern = r'^DOMAIN=.*$'
        new_domain_line = f'DOMAIN={new_domain}'
        updated_content = re.sub(domain_pattern, new_domain_line, file_content, flags=re.MULTILINE)
        
        # 验证替换是否成功
        if new_domain_line not in updated_content:
            raise Exception("未在 .env 中找到可匹配的 DOMAIN 配置行，更新失败")
        
        # 写入更新后的内容
        with open(env_file, "w", encoding="utf-8") as f:
            f.write(updated_content)
        
        print(f"✅ .env 文件更新成功，DOMAIN 已替换为：{new_domain}")
    
    except Exception as e:
        raise Exception(f"❌ .env 文件更新失败：{str(e)}")

def auto_open_cmd_and_run_ip_py():
    """终极方案：用Windows原生命令强制启动IP.py，确保新窗口必弹出，无依赖"""
    try:
        # 获取IP.py完整绝对路径，避免路径错误
        ip_py_full_path = os.path.abspath(TARGET_FILE_PATH)
        
        # 构建Windows原生命令：强制打开新CMD窗口，启动IP.py并保留窗口
        # start命令：Windows原生，比Python subprocess更稳定；cmd /k：执行后保留窗口，方便查看日志
        cmd_command = f'start "IP.py运行窗口" cmd /k "python "{ip_py_full_path}""'
        
        # 执行Windows命令，强制启动新窗口
        os.system(cmd_command)
        
        print(f"🎉 已用Windows原生命令启动IP.py，新CMD窗口已弹出并保留")
        print(f"📌 IP.py运行路径：{ip_py_full_path}")
    
    except Exception as e:
        raise Exception(f"❌ IP.py启动失败：{str(e)}")

def main():
    """主函数：串联所有流程，全自动执行，无手动干预，交由bat确保原窗口关闭"""
    print("=" * 60)
    print("🎉 Cpolar 自动登录+域名提取+IP.py更新+自动启动 工具（终极完整版）")
    print("=" * 60)
    
    try:
        # 步骤1：爬取（登录→导航→提取）有效HTTPS公网域名
        new_cpolar_domain = crawl_cpolar_domain()
        
        # 步骤2：验证提取的域名格式是否合法
        is_valid, validate_msg = validate_domain(new_cpolar_domain)
        if not is_valid:
            print(f"❌ 域名验证失败：{validate_msg}")
            return
        print(f"✅ 域名验证通过：{validate_msg}")
        
        # 步骤3：自动更新.env中的DOMAIN配置（无需手动确认，直接执行）
        print("\n" + "-" * 50)
        print(f"📌 自动更新.env域名配置，无需手动干预...")
        modify_env_file(TARGET_FILE_PATH, new_cpolar_domain)
        
        # 步骤4：用Windows原生命令强制启动IP.py，打开新窗口
        print("\n" + "-" * 50)
        auto_open_cmd_and_run_ip_py()
        
        # 步骤5：流程全部完成，自然结束（由配套bat脚本确保原窗口关闭，无残留）
        print("\n" + "=" * 60)
        print("🎉 所有流程全自动执行完成！")
        print("✅ 最终结果：.env已更新，IP.py已启动，仅保留IP.py运行窗口")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n❌ 脚本执行异常终止：{str(e)}")

# 脚本入口：直接运行触发全自动流程（无内部退出逻辑，交由bat处理窗口关闭）
if __name__ == "__main__":
    main()