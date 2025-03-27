import base64
import logging
import re
import traceback
import json
import os

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QDialog, QMessageBox, QTextEdit, QDesktopWidget, QPushButton, QDialogButtonBox, QCheckBox, QVBoxLayout, QGroupBox, QLabel
from PyQt5.uic import loadUi
from anthropic import Anthropic

from core.dialog.help_dialog import HelpDialog
import requests
from cfg.cfg import *

from utils.state_manager import get_excel_checkbox_state, set_excel_checkbox_state

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super(SettingsDialog, self).__init__(parent)
        # 프로젝트 디렉토리 내에 config 디렉토리 생성
        self.app_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
        if not os.path.exists(self.app_dir):
            os.makedirs(self.app_dir, exist_ok=True)
        self.config_file = os.path.join(self.app_dir, "config.json")
        print(f"Config file path: {os.path.abspath(self.config_file)}")  # 디버깅용
        
        self.setWindowTitle("설정")
        self.setMinimumWidth(400)
        self.setMinimumHeight(400)  # 높이 증가
        
        # 메인 레이아웃
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # API Key 섹션
        api_key_group = QGroupBox("API Key")
        api_key_layout = QVBoxLayout()
        
        self.text_edit_api_key = QTextEdit()
        self.text_edit_api_key.setPlaceholderText("Claude API Key를 입력하세요")
        self.text_edit_api_key.setMaximumHeight(60)
        
        self.validate_api_key_button = QPushButton("API Key 확인")
        self.validate_api_key_button.setMinimumHeight(30)
        
        self.reset_api_key_button = QPushButton("재설정")
        self.reset_api_key_button.setMinimumHeight(30)
        
        api_key_layout.addWidget(self.text_edit_api_key)
        api_key_layout.addWidget(self.validate_api_key_button)
        api_key_layout.addWidget(self.reset_api_key_button)
        api_key_group.setLayout(api_key_layout)

        # 체크박스
        self.show_excel_check = QCheckBox("엑셀 파일 표시")
        self.show_excel_check.setChecked(get_excel_checkbox_state())

        # 버튼 박스
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        
        # 메인 레이아웃에 위젯 추가
        main_layout.addWidget(api_key_group)
        main_layout.addWidget(self.show_excel_check)
        main_layout.addWidget(self.buttonBox)

        # 시그널 연결
        self.show_excel_check.stateChanged.connect(self.update_checkbox_state)
        self.validate_api_key_button.clicked.connect(self.validate_api_key)
        self.buttonBox.accepted.connect(self.save_settings)
        self.buttonBox.rejected.connect(self.reject)
        self.reset_api_key_button.clicked.connect(self.reset_api_key)

        # 초기 상태 설정
        self.api_key_valid = False
        self.update_buttonbox_state()

        # 기존 설정 로드
        self.load_existing_settings()

    def load_existing_settings(self):
        """기존 설정 불러오기"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                    # API 키 설정
                    if 'claude_key' in config and config['claude_key'].strip():
                        self.text_edit_api_key.setText(config['claude_key'])
                        self.api_key_valid = True
                        # 이미 유효한 API 키가 있으면 필드와 버튼 비활성화
                        self.text_edit_api_key.setReadOnly(True)
                        self.validate_api_key_button.setEnabled(False)
                        
                    print(f"기존 설정 불러옴: API Key={bool(config.get('claude_key'))}")
                    
                    # 버튼 상태 업데이트
                    self.update_buttonbox_state()
        except Exception as e:
            print(f"기존 설정 불러오기 오류: {str(e)}")
            # 오류 발생 시 빈 설정 사용 (기본값)

    def update_buttonbox_state(self):
        self.buttonBox.button(QDialogButtonBox.Save).setEnabled(self.api_key_valid)

    def update_checkbox_state(self, state):
        set_excel_checkbox_state(bool(state))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.EnterWhatsThisMode:
            self.show_help_dialog()
            return True
        return super().eventFilter(obj, event)

    def reject(self):
        print("입력 실패")
        super().reject()

    def validate_api_key(self):
        api_key = self.text_edit_api_key.toPlainText().strip()
        self.text_edit_api_key.setReadOnly(True)
        self.validate_api_key_button.setEnabled(False)

        logging.debug(f"Validating API key: {api_key[:5]}...{api_key[-5:]}")

        if not api_key:
            QMessageBox.warning(self, "API Key 오류", "API Key를 입력해주세요.")
            self.api_key_valid = False
            self.text_edit_api_key.setReadOnly(False)
            self.validate_api_key_button.setEnabled(True)
        else:
            try:
                client = Anthropic(api_key=api_key)
                response = client.messages.create(
                    model="claude-3-7-sonnet-20250219",
                    max_tokens=10,
                    messages=[{
                        "role": "user",
                        "content": "Hello"
                    }]
                )
                self.api_key_valid = True
                QMessageBox.information(self, "성공", "API 키가 유효합니다.")
                
                self.text_edit_api_key.setReadOnly(True)
                self.validate_api_key_button.setEnabled(False)
                
                # 저장 버튼 활성화
                self.buttonBox.button(QDialogButtonBox.Save).setEnabled(True)
                
                # 자동으로 저장 다이얼로그 표시
                self.save_settings()
            except Exception as e:
                logging.error(f"Error validating API key: {str(e)}")
                logging.error(traceback.format_exc())
                self.api_key_valid = False
                QMessageBox.critical(self, "오류", f"API 키 검증 중 오류 발생:\n{str(e)}")
                
                self.text_edit_api_key.setReadOnly(False)
                self.validate_api_key_button.setEnabled(True)

        self.update_buttonbox_state()
        logging.debug("API key validation completed")

    def show_help_dialog(self):
        help_content = self.get_help_content()
        help_dialog = HelpDialog("설정 도움말", help_content, self)
        
        screen = QDesktopWidget().screenNumber(QDesktopWidget().cursor().pos())
        center_point = QDesktopWidget().screenGeometry(screen).center()
        frame_geometry = help_dialog.frameGeometry()
        frame_geometry.moveCenter(center_point)
        help_dialog.move(frame_geometry.topLeft())
        help_dialog.exec_()

    def get_help_content(self):
        return """
            <style>
                body {
                    font-family: 'Malgun Gothic', '맑은 고딕', Arial, sans-serif;
                    font-size: 14px;
                }
                h1 {
                    font-size: 24px;
                    color: #333;
                }
                h2 {
                    font-size: 20px;
                    color: #444;
                }
                p, li {
                    font-size: 16px;
                    line-height: 1.5;
                }
                code {
                    background-color: #f0f0f0;
                    padding: 2px 4px;
                    border-radius: 4px;
                }
            </style>
            <h1>설정 도움말</h1>
            <h2>API KEY 확인하는 방법</h2>
            <ol>
                <li>Anthropic 웹사이트(<a href='https://console.anthropic.com/account/keys'>https://console.anthropic.com/account/keys</a>)에 접속하여 로그인 또는 회원가입을 진행합니다.</li>
                <li>API 키 섹션에서 "Create Key" 버튼을 클릭합니다.</li>
                <li>생성된 API 키를 복사하여 설정에 붙여넣습니다.</li>
            </ol>
            <p>주의: API 키는 비밀번호와 같이 중요한 정보이므로 절대 타인과 공유하지 마세요.</p>
        """
    
    def save_settings(self):
        """설정 저장"""
        try:
            if not os.path.exists(self.app_dir):
                os.makedirs(self.app_dir, exist_ok=True)

            api_key = self.text_edit_api_key.toPlainText().strip()
            if not api_key:
                choice = QMessageBox.question(
                    self,
                    "설정 경고",
                    "API 키가 없습니다. 계속 진행하시겠습니까?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if choice == QMessageBox.No:
                    return

            if os.path.exists(self.config_file):
                try:
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                except:
                    settings = {}
            else:
                settings = {}

            settings['claude_key'] = api_key
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
            
            print(f"설정 저장됨: API Key={bool(api_key)}")
            self.accept()
        except Exception as e:
            print(f"설정 저장 중 오류: {str(e)}")
            traceback.print_exc()
            QMessageBox.critical(self, "오류", f"설정을 저장할 수 없습니다: {str(e)}")
            return

    def closeEvent(self, event):
        QMessageBox.warning(self, '경고', '완료되지 않았습니다.', QMessageBox.Ok)
        event.ignore()

    def accept(self):
        set_excel_checkbox_state(self.show_excel_check.isChecked())
        print(f"Settings saved. Excel checkbox state: {get_excel_checkbox_state()}")
        super().accept()

    def reset_api_key(self):
        """API Key 필드 재설정"""
        self.text_edit_api_key.setReadOnly(False)
        self.validate_api_key_button.setEnabled(True)
        self.api_key_valid = False
        self.update_buttonbox_state()
