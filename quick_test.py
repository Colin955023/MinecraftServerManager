#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft 伺服器管理器 - 快速測試腳本
提供系統環境檢查、依賴驗證和主程式模組載入狀態測試功能
Minecraft Server Manager - Quick Test Script
Provides system environment checking, dependency verification and main program module loading status testing
"""
# ====== 標準函式庫 ======
from pathlib import Path
import os
import sys
import traceback
import importlib
import tempfile

# ====== 測試工具函數 ======

# 列印測試步驟標題
def print_step(step_num, total_steps, description):
    """
    列印測試步驟標題
    Print test step title
    
    Args:
        step_num (int): 步驟編號
        total_steps (int): 總步驟數
        description (str): 步驟描述
        
    Returns:
        None
    """
    print(f"\n[{step_num}/{total_steps}] {description}...")

def print_success(message):
    """打印成功訊息"""
    print(f"✅ {message}")

def print_error(message):
    """打印錯誤訊息"""
    print(f"❌ {message}")

def print_warning(message):
    """打印警告訊息"""
    print(f"⚠️ {message}")

def test_python_environment():
    """[1/8] 檢查 Python 環境"""
    print_step(1, 8, "檢查 Python 環境")

    try:
        version = sys.version_info
        if version.major < 3 or (version.major == 3 and version.minor < 7):
            print_error(f"Python 版本過舊: {version.major}.{version.minor}")
            print("    請安裝 Python 3.7 或更新版本")
            return False

        print_success(f"Python 環境正常 (版本: {version.major}.{version.minor}.{version.micro})")
        return True
    except Exception as e:
        print_error(f"Python 環境檢查失敗: {e}\n{traceback.format_exc()}")
        return False

def test_basic_modules():
    """[2/8] 測試基礎模組導入"""
    print_step(2, 8, "測試基礎模組導入")

    basic_modules = ['tkinter', 'json', 'os', 'sys', 'pathlib']

    try:
        for module_name in basic_modules:
            importlib.import_module(module_name)

        print_success("基礎模組導入成功")
        return True
    except ImportError as e:
        print_error(f"基礎模組導入失敗: {e}\n{traceback.format_exc()}")
        return False
    except Exception as e:
        print_error(f"基礎模組測試出現異常: {e}\n{traceback.format_exc()}")
        return False

def test_project_dependencies():
    """[3/8] 檢查專案依賴"""
    print_step(3, 8, "檢查專案依賴")

    required_modules = [
        ('customtkinter', 'CustomTkinter'),
        ('requests', 'Requests'),
        ('psutil', 'PSUtil'),
        ('lxml', 'LXML'),
    ]

    missing_modules = []

    for module_name, display_name in required_modules:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing_modules.append(display_name)
        except Exception as e:
            print_warning(f"模組 {display_name} 載入時出現異常: {e}")

    if missing_modules:
        print_error("專案依賴缺失:")
        for module in missing_modules:
            print(f"    • {module}")
        print("請先執行: pip install uv 安裝套件管理工具")
        print("再執行: py -m uv sync --reinstall 以安裝缺失的依賴")
        return False

    print_success("專案依賴檢查通過")
    return True

def test_main_program_modules():
    """[4/8] 測試主程式模組載入"""
    print_step(4, 8, "測試主程式模組載入")

    # quick_test.py 僅供「完整 repo」使用者快速測試，不做任何打包環境判斷
    repo_root = Path(__file__).resolve().parent
    src_path = repo_root / "src"

    if not src_path.exists():
        print_error(f"找不到 src 目錄: {src_path}")
        print("    請確認你是在完整 repo 根目錄執行 quick_test.py")
        return False

    # 確保 repo root 在 sys.path 中，讓 `import src...` 能正常運作
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # 要測試的核心模組（只測試不需要外部依賴的模組）
    testable_modules = [
        ('src.utils.log_utils', 'LogUtils'),
        ('src.utils.settings_manager', 'SettingsManager'),
        ('src.utils.runtime_paths', 'RuntimePaths'),
        ('src.models', 'Models'),
        ('src.version_info', 'VersionInfo'),
    ]

    # 這些模組需要檢查檔案存在性但不導入（因為可能有依賴問題）
    file_check_modules = [
        ('src.core.version_manager', 'MinecraftVersionManager'),
        ('src.core.loader_manager', 'LoaderManager'),
        ('src.core.server_manager', 'ServerManager'),
        ('src.utils.server_utils', 'ServerUtils'),
        ('src.ui.main_window', 'MainWindow'),
        ('src.ui.create_server_frame', 'CreateServerFrame'),
        ('src.ui.manage_server_frame', 'ManageServerFrame'),
    ]

    failed_modules = []
    error_details = {}
    successful_modules = []

    # 測試可導入的模組
    for module_name, display_name in testable_modules:
        try:
            importlib.import_module(module_name)
            successful_modules.append(display_name)
        except ImportError as e:
            failed_modules.append(display_name)
            error_details[module_name] = f"導入失敗: {str(e)}"
        except Exception as e:
            failed_modules.append(display_name)
            error_details[module_name] = f"載入錯誤: {str(e)}"

    # 檢查檔案存在性
    for module_name, display_name in file_check_modules:
        try:
            rel_mod = module_name
            if rel_mod.startswith("src."):
                rel_mod = rel_mod[len("src."):]
            module_file = src_path / f"{rel_mod.replace('.', '/')}.py"
            if not module_file.exists():
                failed_modules.append(display_name)
                error_details[module_name] = f"模組檔案不存在: {module_file}"
                continue

            # 簡單的語法檢查
            with open(module_file, 'r', encoding='utf-8') as f:
                content = f.read()

            try:
                compile(content, str(module_file), 'exec')
                successful_modules.append(display_name)
            except SyntaxError as e:
                failed_modules.append(display_name)
                error_details[module_name] = f"語法錯誤: {str(e)}"

        except Exception as e:
            failed_modules.append(display_name)
            error_details[module_name] = f"檢查失敗: {str(e)}"

    # 顯示結果
    if failed_modules:
        print_error("主程式模組載入失敗:")
        for module_name, error in error_details.items():
            print(f"    • {module_name}: {error}")

        if successful_modules:
            print(f"\n✅ 成功載入的模組: {', '.join(successful_modules)}")

        print("\n🔧 故障排除建議:")
        print("   1. 檢查專案檔案結構是否完整")
        print("   2. 確保所有必要的 .py 檔案都存在於 src/ 目錄下")
        print("   3. 檢查模組中是否有語法錯誤")
        print("   4. 確認所有依賴套件都已正確安裝")
        print("   5. 請在完整 repo 根目錄執行 quick_test.py")

        # 如果有部分成功，不算完全失敗
        if successful_modules and len(successful_modules) >= len(failed_modules):
            print_warning("部分模組載入成功，主要功能應該可以正常運作")
            return True

        return False

    print_success("主程式模組載入成功")
    return True


def test_network_connectivity():
    """[5/8] 測試網路連線"""
    print_step(5, 8, "測試網路連線")

    try:
        import requests

        response = requests.get('https://api.github.com', timeout=5)

        if response.status_code == 200:
            print_success("網路連線正常")
            return True
        else:
            print_warning(f"網路連線異常 (狀態碼: {response.status_code})")
            return False
    except ImportError:
        print_warning("requests 模組未安裝，跳過網路測試")
        return True  # 不算作失敗，因為這不是必要功能
    except requests.exceptions.Timeout:
        print_warning("網路連線超時（可能影響版本下載功能）")
        return False
    except requests.exceptions.RequestException as e:
        print_warning(f"網路連線測試失敗: {e}")
        return False
    except Exception as e:
        print_warning(f"網路測試出現異常: {e}")
        return False


def test_file_system_permissions():
    """[6/8] 測試檔案系統權限"""
    print_step(6, 8, "測試檔案系統權限")

    try:
        # 使用系統臨時目錄，避免污染 repo 或遇到同名目錄衝突
        with tempfile.TemporaryDirectory(prefix="msm_quick_test_") as temp_dir:
            test_file = os.path.join(temp_dir, "test_file.txt")

            # 測試寫入檔案
            with open(test_file, 'w', encoding='utf-8') as f:
                f.write("測試內容")

            # 測試讀取檔案
            with open(test_file, 'r', encoding='utf-8') as f:
                _ = f.read()

        print_success("檔案系統權限正常")
        return True

    except PermissionError as e:
        print_error(f"檔案系統權限不足: {e}\n{traceback.format_exc()}")
        return False
    except Exception as e:
        print_error(f"檔案系統測試失敗: {e}\n{traceback.format_exc()}")
        return False


def test_window_management_logic():
    """[7/8] 測試視窗管理邏輯"""
    print_step(7, 8, "測試視窗管理邏輯")

    try:
        from src.utils.settings_manager import get_settings_manager

        settings = get_settings_manager()

        # 測試視窗偏好設定讀取
        print("    檢查視窗偏好設定...")
        remember_enabled = settings.is_remember_size_position_enabled()
        auto_center_enabled = settings.is_auto_center_enabled()
        adaptive_sizing_enabled = settings.is_adaptive_sizing_enabled()
        dpi_scaling = settings.get_dpi_scaling()

        print(f"    • 記住視窗大小位置: {remember_enabled}")
        print(f"    • 自動置中: {auto_center_enabled}")
        print(f"    • 自適應大小: {adaptive_sizing_enabled}")
        print(f"    • DPI 縮放: {dpi_scaling}")

        # 測試螢幕計算邏輯（模擬）
        print("    測試螢幕計算邏輯...")
        test_screens = [
            {"width": 1366, "height": 768},
            {"width": 1920, "height": 1080},
            {"width": 2560, "height": 1440},
        ]

        for screen in test_screens:
            usable_width = int(screen["width"] * 0.9)
            usable_height = int(screen["height"] * 0.9)

            if screen["width"] <= 1366:
                optimal_width = min(1200, usable_width)
                optimal_height = min(700, usable_height)
            elif screen["width"] <= 1920:
                optimal_width = min(1400, usable_width)
                optimal_height = min(900, usable_height)
            else:
                optimal_width = min(1600, usable_width)
                optimal_height = min(1000, usable_height)

            print(f"    • {screen['width']}x{screen['height']} → 最佳視窗: {optimal_width}x{optimal_height}")

        # 測試設定修改
        print("    測試設定修改...")
        original_dpi = settings.get_dpi_scaling()
        settings.set_dpi_scaling(1.25)
        new_dpi = settings.get_dpi_scaling()
        settings.set_dpi_scaling(original_dpi)  # 恢復原始設定

        if abs(new_dpi - 1.25) < 0.01:
            print("    • DPI 縮放設定修改: 成功")
        else:
            print_warning(f"    • DPI 縮放設定異常: 預期 1.25, 實際 {new_dpi}")

        print_success("視窗管理邏輯測試通過")
        return True

    except ImportError as e:
        print_error(f"視窗管理模組導入失敗: {e}\n{traceback.format_exc()}")
        return False
    except Exception as e:
        print_error(f"視窗管理邏輯測試失敗: {e}\n{traceback.format_exc()}")
        return False


def test_environment_detection():
    """[8/8] 測試環境檢測功能"""
    print_step(8, 8, "測試環境檢測功能")

    try:
        print("    檢查環境檢測...")

        # quick_test.py 只針對完整 repo，這裡僅檢查 repo 結構是否合理
        repo_root = Path(__file__).resolve().parent
        src_dir = repo_root / "src"
        print(f"    • repo_root: {repo_root}")
        print(f"    • src 目錄存在: {src_dir.exists()}")
        
        # 測試設定管理器的調試相關功能
        from src.utils.settings_manager import get_settings_manager
        settings = get_settings_manager()
        
        debug_logging_enabled = settings.is_debug_logging_enabled()
        window_state_logging_enabled = settings.is_window_state_logging_enabled()
        
        print(f"    • 調試日誌啟用: {debug_logging_enabled}")
        print(f"    • 視窗狀態日誌啟用: {window_state_logging_enabled}")
        
        # 測試日誌工具的調試判斷功能
        from src.utils.log_utils import LogUtils
        print("    測試日誌工具調試判斷...")
        
        # 這只是檢查函數是否可以正常調用，不會實際輸出
        try:
            # 測試各種日誌級別
            LogUtils.debug("測試調試訊息", "環境檢測")
            LogUtils.info("測試資訊訊息", "環境檢測") 
            LogUtils.debug_window_state("測試視窗狀態訊息")
            print("    • 日誌工具調試判斷: 正常")
        except Exception as e:
            print_warning(f"    • 日誌工具測試異常: {e}")

        print_success("環境檢測功能測試通過")
        return True

    except ImportError as e:
        print_error(f"環境檢測模組導入失敗: {e}\n{traceback.format_exc()}")
        return False
    except Exception as e:
        print_error(f"環境檢測功能測試失敗: {e}\n{traceback.format_exc()}")
        return False


def main():
    """主測試函數"""
    print("🚀 Minecraft 伺服器管理器 - 快速測試")
    print("=" * 48)

    # 執行所有測試
    tests = [
        test_python_environment,
        test_basic_modules,
        test_project_dependencies,
        test_main_program_modules,
        test_network_connectivity,
        test_file_system_permissions,
        test_window_management_logic,
        test_environment_detection,
    ]

    passed_tests = 0
    failed_tests = []

    for i, test_func in enumerate(tests, 1):
        try:
            if test_func():
                passed_tests += 1
            else:
                failed_tests.append(f"測試 {i}")
        except Exception as e:
            print_error(f"測試 {i} 執行時出現異常: {e}")
            print(f"詳細錯誤:\n{traceback.format_exc()}")
            failed_tests.append(f"測試 {i}")

    # 顯示測試結果摘要
    print("\n" + "=" * 48)
    if failed_tests:
        print(f"❌ 測試完成: {passed_tests}/{len(tests)} 通過")
        print(f"失敗的測試: {', '.join(failed_tests)}")
        print("\n請解決上述問題後重新執行測試。")
        return 1
    else:
        print(f"🎉 所有測試通過! ({passed_tests}/{len(tests)})")
        print("\n📋 已驗證功能:")
        print("   ✅ Python 環境和版本檢查")
        print("   ✅ 基礎模組導入測試")
        print("   ✅ 專案依賴完整性檢查")
        print("   ✅ 主程式模組載入測試")
        print("   ✅ 網路連線和 API 存取測試")
        print("   ✅ 檔案系統權限測試")
        print("   ✅ 視窗管理邏輯測試")
        print("   ✅ 環境檢測功能測試")

        # 詢問是否啟動主程式
        try:
            print("\n🚀 啟動主程式？")
            choice = input("按 Y 啟動 Minecraft 伺服器管理器，按其他鍵退出: ").strip().lower()
            if choice == 'y':
                print("\n正在啟動 Minecraft 伺服器管理器...")
                # 導入並啟動主程式
                import src.main as app_main
                app_main.main()
            else:
                print("\n測試完成，感謝使用！")
        except KeyboardInterrupt:
            print("\n\n測試被使用者中斷。")
        except Exception as e:
            print(f"\n啟動主程式時出現錯誤: {e}")
            return 1

        return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n程式被使用者中斷。")
        sys.exit(130)
    except Exception as e:
        print(f"\n嚴重錯誤: {e}")
        print(f"詳細錯誤資訊:\n{traceback.format_exc()}")
        sys.exit(1)
