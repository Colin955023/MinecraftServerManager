#!/usr/bin/env python3
"""應用層共用異常型別。"""

from __future__ import annotations


class AppException(Exception):
    """應用程式層的基底異常。"""


class ConfigurationError(AppException):
    """設定無效、缺失或無法使用。"""


class NetworkOperationError(AppException):
    """網路操作失敗。"""


class MetadataResolutionError(AppException):
    """metadata 解析或補齊失敗。"""


class ServerOperationError(AppException):
    """伺服器建立、啟動、更新或刪除流程失敗。"""
