# ===================== CLIP 视觉模型模块 =====================
# 加载 CLIP (ViT-B/32) 模型到 CPU，对图片进行多标签分类分析
# 返回图片的语义标签和最佳描述

from io import BytesIO  # 字节流：将图片二进制数据转为 PIL Image
import asyncio  # 异步 IO：在子线程中运行 CLIP 推理，避免阻塞事件循环
from .config import CLIP_IMAGE_TAGS  # 候选标签列表（约200个）
from .log import log_system, log_api, log_err  # 日志
import botv.config as cfg  # 全局运行时变量

clip_model = None  # CLIP 模型实例（全局单例）
clip_processor = None  # CLIP 图片处理器（全局单例）
_clip_module = None  # CLIP 库模块引用（用于调用 tokenize 等函数）
cfg.CLIP_ENABLED = False  # CLIP 是否可用（全局标志）

def init_clip_model():
    """初始化 CLIP 模型：加载 ViT-B/32 到 CPU，设置 eval 模式"""
    global clip_model, clip_processor, _clip_module
    try:
        import torch, clip  # 导入 PyTorch 和 OpenAI CLIP 库
        log_system("加载 CLIP (CPU)...")
        clip_model, clip_processor = clip.load("ViT-B/32", device="cpu")  # 加载模型和处理器
        clip_model.eval()  # 设置为评估模式（禁用 dropout）
        _clip_module = clip  # 保存库引用
        cfg.CLIP_ENABLED = True  # 标记 CLIP 可用
        log_system("CLIP 加载完成")
    except Exception as e:
        cfg.CLIP_ENABLED = False  # 加载失败，标记不可用
        log_system(f"CLIP加载失败(不影响运行): {e}")

async def analyze_image_with_clip(image_data: bytes, custom_tags: list = None) -> tuple:
    """CLIP 分析图片，返回 (tags 列表, 最佳描述)
    
    参数：
        image_data: 图片二进制数据
        custom_tags: 自定义候选标签列表（默认使用 CLIP_IMAGE_TAGS）
    返回：
        (tags, desc) 元组，tags 为得分最高的标签列表，desc 为最佳描述
    """
    if not cfg.CLIP_ENABLED:  # CLIP 未加载
        return ["表情包"], "图片"  # 返回默认值
    try:
        from PIL import Image as PilImage  # PIL 图片处理
        import torch  # PyTorch 张量操作
        img = PilImage.open(BytesIO(image_data)).convert("RGB")  # 打开图片并转为 RGB
        tags = custom_tags or CLIP_IMAGE_TAGS  # 使用自定义标签或默认标签
        
        def _run():
            """同步 CLIP 推理函数（在子线程中运行）"""
            clip = _clip_module
            # OpenAI clip 库: preprocess (Compose) 直接返回 tensor [C,H,W]
            inp = clip_processor(img).unsqueeze(0)  # [C,H,W] -> [1,C,H,W]
            txt = clip.tokenize(tags)  # 将标签列表转为 token 张量
            with torch.no_grad():  # 禁用梯度计算（推理模式）
                img_f = clip_model.encode_image(inp)  # 编码图片特征
                txt_f = clip_model.encode_text(txt)  # 编码文本特征
            img_f /= img_f.norm(dim=-1, keepdim=True)  # L2 归一化
            txt_f /= txt_f.norm(dim=-1, keepdim=True)  # L2 归一化
            return (100.0 * img_f @ txt_f.T).softmax(dim=-1)[0].tolist()  # 计算相似度并 softmax
        
        scores = await asyncio.to_thread(_run)  # 在子线程中执行推理
        idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)  # 按得分降序排序
        best_tags = [tags[i] for i in idx[:3] if scores[i] > 0.01]  # 取得分 > 0.01 的前3个标签
        desc = tags[idx[0]] if idx else "图片"  # 最高分标签作为描述
        if not best_tags:
            best_tags = ["表情包"]  # 无有效标签时兜底
        log_api(f"CLIP: {best_tags}")  # 日志记录
        return best_tags, desc
    except Exception as e:
        log_err(f"CLIP失败: {e}")  # 异常记录
        return ["表情包"], "图片"  # 返回默认值
