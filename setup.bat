@echo off
echo ========================================
echo FactorGuard MVP 环境初始化
echo ========================================

REM 创建虚拟环境
python -m venv venv

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 升级 pip
python -m pip install --upgrade pip

REM 安装依赖
pip install -r requirements.txt

echo.
echo ========================================
echo 环境初始化完成！
echo 运行命令: venv\Scripts\activate.bat
echo 启动应用: streamlit run app.py
echo ========================================
pause