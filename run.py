# ===================== 模块入口 =====================
# 友利奈绪 QQ 机器人 v5 — CLIP视觉识图 + 简短动作回复
# 不导入任何模块，避免循环依赖
# 所有子模块通过 botv.xxx 方式导入

import sys
import subprocess
import importlib.util

# ===================== 依赖检查与自动安装 =====================
# 项目所需的所有依赖包列表
REQUIRED_PACKAGES = [
    "websockets",       # WebSocket 服务器
    "requests",         # HTTP 请求
    "urllib3",          # HTTP 底层库
    "pymysql",          # MySQL 数据库
    "jieba",            # 中文分词
    "Pillow",           # 图片处理（PIL）
    "chinesecalendar",  # 中国节假日判断（可选，降级为 weekday）
    "aiohttp",          # HTTP API 服务器
]

# 可选依赖（安装失败不影响主流程）
OPTIONAL_PACKAGES = [
    "torch",            # PyTorch（CLIP 模型需要）
    "transformers",     # HuggingFace Transformers（CLIP 处理器需要）
]

def check_and_install(package_name, optional=False):
    """检查包是否已安装，未安装则自动 pip install"""
    # 特殊处理：Pillow 的 import 名是 PIL
    import_name = package_name
    if package_name == "Pillow" or package_name == "PIL":
        import_name = "PIL"
    
    try:
        importlib.import_module(import_name)
        return True  # 已安装
    except ImportError:
        pass
    
    # 未安装，尝试自动安装
    tag = "[可选]" if optional else "[必需]"
    print(f"{tag} 正在安装 {package_name}...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package_name, "-q"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"  ✅ {package_name} 安装成功")
        return True
    except Exception as e:
        if optional:
            print(f"  ⚠️ {package_name} 安装失败（可选，跳过）: {e}")
            return False
        else:
            print(f"  ❌ {package_name} 安装失败: {e}")
            print(f"  💡 请手动执行: pip install {package_name}")
            return False

def check_all_dependencies():
    """检查并安装所有依赖"""
    print("=" * 50)
    print("  🤖 友利奈绪 QQ 机器人 — 依赖检查")
    print("=" * 50)
    print()
    
    all_ok = True
    
    # 检查必需依赖
    print("📦 必需依赖：")
    for pkg in REQUIRED_PACKAGES:
        if not check_and_install(pkg, optional=False):
            all_ok = False
    
    print()
    
    # 检查可选依赖
    print("📦 可选依赖（不影响基础功能）：")
    for pkg in OPTIONAL_PACKAGES:
        check_and_install(pkg, optional=True)
    
    print()
    
    if all_ok:
        print("✅ 所有必需依赖已就绪，启动机器人...")
    else:
        print("⚠️ 部分依赖安装失败，请手动安装后重试")
        print("   命令: pip install -r requirements.txt")
    
    print("=" * 50)
    print()
    return all_ok


# ===================== 启动入口 =====================
import asyncio

if __name__ == "__main__":
    # 先检查依赖
    if not check_all_dependencies():
        sys.exit(1)
    # 依赖检查通过后再导入主模块
    from botv.main import main
    # 启动机器人
    asyncio.run(main())
