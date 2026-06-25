# 所有子模块通过 botv.xxx 方式导入

import asyncio
from botv.main import main

if __name__ == "__main__":
    asyncio.run(main())