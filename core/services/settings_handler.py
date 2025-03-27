# 설정 관련 기능들을 묶어 분할한다.
import os
import json
import traceback

from PyQt5.QtWidgets import QFileDialog, QVBoxLayout, QWidget, QDialog, QMessageBox
from core.dialog.setting_dialog import SettingsDialog

class SettingsHandler:
    def __init__(self, main_ui, config_file):
        self.main_ui = main_ui
        self.config_file = config_file
        self.settings = {}
        self.load_settings()

    def load_settings(self):
        """설정 파일 로드"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
                print(f"설정 파일 로드 완료: {self.config_file}")
            else:
                print(f"설정 파일이 없습니다. 새로 생성합니다: {self.config_file}")
                self.save_settings()
        except Exception as e:
            print(f"설정 파일 로드 중 오류 발생: {e}")
            self.settings = {}
            self.save_settings()

    def save_settings(self):
        """설정 파일 저장"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
            print(f"설정 파일 저장 완료: {self.config_file}")
        except Exception as e:
            print(f"설정 파일 저장 중 오류 발생: {e}")
            QMessageBox.critical(self.main_ui, '오류', f'설정을 저장할 수 없습니다: {str(e)}')

    def check_settings(self):
        if not os.path.exists(self.config_file):
            return False
        with open(self.config_file, 'r') as f:
            config = json.load(f)
        return bool(config.get('claude_key'))

    def save_setting(self, key, value):
        """단일 설정값 저장"""
        old_value = self.settings.get(key)
        if old_value != value:  # 값이 변경된 경우에만 저장
            self.settings[key] = value
            print(f"설정 변경: {key} = {value}")
            return self.save_settings()
        return True

    def get_setting(self, key, default=None):
        """설정값 가져오기"""
        value = self.settings.get(key, default)
        # 디렉토리 경로인 경우 유효성 확인
        if key in ['load_dir', 'last_save_directory'] and value:
            if not os.path.exists(value):
                print(f"경고: 요청한 디렉토리 경로가 존재하지 않음 - {key}: {value}")
                # 사용자 홈 디렉토리로 대체
                if default is None:
                    return os.path.expanduser('~')
        return value

    def open_settings_dialog(self):
        settings_dialog = SettingsDialog(self.main_ui)
        result = settings_dialog.exec_()
        if result == QDialog.Accepted:
            # 설정이 저장된 후 즉시 새로운 설정을 로드하고 반환
            api_key = self.load_settings()
            if api_key:
                print(f"Loaded API key after saving: {bool(api_key)}")  # 디버깅용
                return result
        return result

    def get_default_settings(self):
        """기본 설정 반환"""
        return {
            "claude_key": "",
            "auto_save": False,
            "last_save_directory": os.path.expanduser("~")
        }
