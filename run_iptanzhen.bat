@echo off
chcp 65001 >nul
echo 正在启动Cpolar全自动更新工具
echo ================================================
:: 获取当前 bat 文件所在目录，自动切换到该目录
cd /d "%~dp0"
:: 设置Python使用UTF-8编码
set PYTHONIOENCODING=utf-8
:: 使用虚拟环境运行 Python 脚本
start "Cpolar更新工具" /MIN .\venv\Scripts\python.exe "Upgrade-ip.py"
:: 当前bat窗口立即退出
exit
