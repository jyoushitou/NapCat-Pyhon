# CLIP 模型（CPU）加载与图片分析
from io import BytesIO
import asyncio
from .config import CLIP_IMAGE_TAGS
from .log import log_system, log_api, log_err

CLIP_ENABLED=False; clip_model=None; clip_processor=None

def init_clip_model():
    global CLIP_ENABLED,clip_model,clip_processor
    try:
        import torch,clip
        log_system("加载 CLIP (CPU)...")
        clip_model,clip_processor=clip.load("ViT-B/32",device="cpu")
        clip_model.eval(); CLIP_ENABLED=True
        log_system("CLIP 加载完成")
    except Exception as e:
        CLIP_ENABLED=False; log_system(f"CLIP加载失败(不影响运行): {e}")

async def analyze_image_with_clip(image_data:bytes,custom_tags:list=None)->tuple:
    """CLIP分析图片，返回(tags列表,描述)"""
    if not CLIP_ENABLED: return ["表情包"],"图片"
    try:
        from PIL import Image as PilImage
        import torch
        img=PilImage.open(BytesIO(image_data)).convert("RGB")
        tags=custom_tags or CLIP_IMAGE_TAGS
        def _run():
            inp=clip_processor(images=img,return_tensors="pt")
            txt=clip.tokenize(tags)
            with torch.no_grad():
                img_f=clip_model.encode_image(inp["pixel_values"])
                txt_f=clip_model.encode_text(txt)
            img_f/=img_f.norm(dim=-1,keepdim=True)
            txt_f/=txt_f.norm(dim=-1,keepdim=True)
            return (100.0*img_f@txt_f.T).softmax(dim=-1)[0].tolist()
        scores=await asyncio.to_thread(_run)
        idx=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
        best_tags=[tags[i] for i in idx[:3] if scores[i]>0.01]
        desc=tags[idx[0]] if idx else "图片"
        if not best_tags: best_tags=["表情包"]
        log_api(f"CLIP: {best_tags}")
        return best_tags,desc
    except Exception as e:
        log_err(f"CLIP失败: {e}"); return ["表情包"],"图片"

