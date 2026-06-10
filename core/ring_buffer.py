"""采集、解析和日志线程之间使用的线程安全环形缓冲区。"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any


class RingBuffer:
    """
    线程安全的固定容量环形缓冲区。

    非阻塞写入是实时采集链路的默认模式：当缓冲区已满时，新数据会进入队列，
    最旧的数据由 ``deque(maxlen=...)`` 自动淘汰，避免网络或串口接收线程被慢消费者拖住。

    Args:
        maxsize: 缓冲区最大元素数量。
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self.maxsize = maxsize
        self.buffer: deque[Any] = deque(maxlen=maxsize)
        self.lock = threading.Lock()
        self.not_empty = threading.Condition(self.lock)
        self.not_full = threading.Condition(self.lock)
        self.closed = False

    def put(self, item: Any, block: bool = False, timeout: float | None = None) -> bool:
        """
        写入一个元素。

        Args:
            item: 待写入的数据。
            block: 是否在缓冲区满时等待空间。
            timeout: 阻塞等待超时时间，仅在 ``block=True`` 时生效。

        Returns:
            是否写入成功。
        """
        with self.not_full:
            if self.closed:
                return False

            if not block:
                self.buffer.append(item)
                self.not_empty.notify()
                return True

            if len(self.buffer) >= self.maxsize and not self.not_full.wait(timeout):
                return False

            self.buffer.append(item)
            self.not_empty.notify()
            return True

    def get(self, block: bool = True, timeout: float | None = None) -> Any | None:
        """
        读取一个元素。

        Args:
            block: 缓冲区为空时是否等待数据。
            timeout: 阻塞等待超时时间。

        Returns:
            读取到的数据；无数据或缓冲区关闭时返回 None。
        """
        with self.not_empty:
            if not block:
                if not self.buffer:
                    return None
                item = self.buffer.popleft()
                self.not_full.notify()
                return item

            while not self.buffer:
                if self.closed:
                    return None
                if not self.not_empty.wait(timeout):
                    return None

            item = self.buffer.popleft()
            self.not_full.notify()
            return item

    def qsize(self) -> int:
        """返回当前缓冲区元素数量。"""
        with self.lock:
            return len(self.buffer)

    def empty(self) -> bool:
        """检查缓冲区是否为空。"""
        with self.lock:
            return not self.buffer

    def full(self) -> bool:
        """检查缓冲区是否已满。"""
        with self.lock:
            return len(self.buffer) >= self.maxsize

    def close(self) -> None:
        """关闭缓冲区并唤醒所有等待线程。"""
        with self.lock:
            self.closed = True
            self.not_empty.notify_all()
            self.not_full.notify_all()

    def clear(self) -> None:
        """清空缓冲区内容。"""
        with self.lock:
            self.buffer.clear()
            self.not_full.notify_all()
