#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fix signal calls in workers.py to use safe versions
"""
import re

with open('ui/monitoring/workers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 替换所有的 self.signals.log_signal.emit 到 self._safe_emit_log
content = re.sub(
    r'self\.signals\.log_signal\.emit\(',
    'self._safe_emit_log(',
    content
)

# 替换所有的 self.signals.status_signal.emit(self.name, 到 self._safe_emit_status(
content = re.sub(
    r'self\.signals\.status_signal\.emit\(self\.name,',
    'self._safe_emit_status(',
    content
)

# 替换所有的 self.signals.epoch_signal.emit 到 self._safe_emit_epoch
content = re.sub(
    r'self\.signals\.epoch_signal\.emit\(',
    'self._safe_emit_epoch(',
    content
)

with open('ui/monitoring/workers.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ 替换完成")
