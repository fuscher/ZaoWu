"""共享数据文件写入锁 — 供 chat.py 和 agent_service.py 共用。

conversations.json 的读写需要跨模块互斥：
- routes/chat.py 写用户消息
- agent_modules/agent_core/agent_service.py 写助手消息 + tool 结果

此模块只提供锁对象，不包含任何业务逻辑。
"""

import threading

# 保护 conversations.json 写入的全局锁
conversation_lock = threading.Lock()
