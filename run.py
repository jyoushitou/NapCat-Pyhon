import asyncio
from botv.main import main
from botv.db import get_cursor
from botv.log import log_system, log_err

if __name__ == "__main__":
    # 确保 ai_raw_responses 表存在（保存AI原始返回数据）
    try:
        c = get_cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_raw_responses (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                model_name VARCHAR(64) NOT NULL DEFAULT '',
                user_msg TEXT,
                raw_response_json LONGTEXT COMMENT 'AI API返回的完整原始JSON数据',
                response_text TEXT COMMENT 'AI回复的文本内容（抽取后的）',
                target_id VARCHAR(64) DEFAULT '' COMMENT '对话目标ID',
                status VARCHAR(32) DEFAULT 'success' COMMENT '状态: success/empty_reply/http_error_xxx/no_api_key',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_created_at (created_at),
                INDEX idx_model_name (model_name),
                INDEX idx_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        c.connection.commit()
        log_system("ai_raw_responses 表已就绪")
    except Exception as e:
        log_err(f"建表失败: {e}")

    asyncio.run(main())
