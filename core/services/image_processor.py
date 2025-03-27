# core/services/image_processor.py

import os
import logging
import time  # datetime.time 대신 time 모듈 직접 import
import traceback
import json
import re

from core.dialog.response_select_dialog import ResponseSelectorDialog
from core.dialog.progress_bar_dialog import ProgressBarDialog
from PyQt5.QtWidgets import QProgressDialog, QMessageBox, QDialog, QFileDialog
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from utils.worker_thread_chat_completion import WorkerThreadChatCompletion  # 새로운 import 추가
import pandas as pd
from anthropic import Anthropic
from PyQt5.QtWidgets import QApplication
import openpyxl


class ImageProcessor(QObject):
    progress_updated = pyqtSignal(int)
    process_finished = pyqtSignal()
    error_occurred = pyqtSignal(str)
    status_signal = pyqtSignal(str)

    def __init__(self, main_ui, settings_handler):
        super().__init__()
        self.main_ui = main_ui
        self.settings_handler = settings_handler
        self.progress_dialog = None
        self.worker = None
        self.results = []
        self.processed_files = set()  # 처리된 파일 추적을 위한 set 추가
        self.processing_completed = False  # 처리 완료 상태 추적을 위한 플래그 추가
        self.setup_logger()
        
        # 마지막 저장 위치 가져오기
        try:
            self.last_save_directory = self.settings_handler.get_setting('last_save_directory')
            if not self.last_save_directory:  # 설정이 없는 경우
                self.last_save_directory = os.path.expanduser('~')
        except:
            self.last_save_directory = os.path.expanduser('~')
        
        # API 키를 settings_handler에서 가져옴
        self.api_key = self.settings_handler.get_setting('claude_key')
        self.client = None
        
        # API 키가 있을 때만 클라이언트 초기화
        if self.api_key:
            try:
                self.client = Anthropic(api_key=self.api_key)
            except Exception as e:
                self.logger.error(f"Failed to initialize Anthropic client: {e}")

    def setup_logger(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    def process_images(self, image_paths):
        """이미지 처리 시작"""
        try:
            # 새로운 처리 시작 시 초기화
            self.results = []
            self.processed_files.clear()  # 처리된 파일 목록도 초기화
            self.processing_completed = False  # 처리 완료 상태 초기화
            
            # API 키 확인
            self.api_key = self.settings_handler.get_setting('claude_key')
            if not self.api_key:
                raise ValueError("API 키가 설정되지 않았습니다.")

            # 이전 worker가 있다면 정리
            if self.worker:
                self.worker.stop()
                self.worker.wait()
                self.worker = None

            # 이전 progress_dialog가 있다면 정리
            if self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None

            # 진행 상황 다이얼로그 생성 및 표시
            try:
                self.progress_dialog = ProgressBarDialog(len(image_paths), self.main_ui)
                self.progress_dialog.setWindowModality(Qt.ApplicationModal)
                
                # 초기 로그 추가
                self.progress_dialog.add_log(f"총 {len(image_paths)}개의 이미지 처리를 시작합니다.")
                
                # Worker 스레드 생성
                self.worker = WorkerThreadChatCompletion(
                    settings_handler=self.settings_handler,
                    image_processor=self
                )

                if not self.worker:
                    raise ValueError("Worker thread creation failed")
                
                # 이미지 경로를 큐에 추가
                for image_path in image_paths:
                    self.worker.queue.put(image_path)
                
                # 시그널 연결
                self.worker.progress.connect(self.progress_dialog.update_progress)
                self.worker.current_file.connect(self.progress_dialog.update_current_file)
                self.worker.result_signal.connect(self.handle_result)
                self.worker.error.connect(self.handle_error)
                self.worker.finished.connect(self.process_complete)
                self.worker.status_signal.connect(self.progress_dialog.add_log)
                self.worker.increment_progress_signal.connect(self.update_progress_incremental)
                
                # 취소 버튼 연결
                self.progress_dialog.cancel_button.clicked.connect(self.worker.stop)
                
                # 다이얼로그 표시
                self.progress_dialog.show()
                QApplication.processEvents()
                
                # Worker 시작
                self.worker.start()

            except Exception as e:
                self.logger.error(f"Error creating progress dialog: {e}")
                raise

        except Exception as e:
            self.logger.error(f"Error in process_images: {e}")
            self.error_occurred.emit(str(e))
            self.cleanup()

    def parse_response(self, response):
        """API 응답 파싱"""
        try:
            print(f"\n[parse_response] 응답 타입: {type(response)}")
            
            # 응답이 None인 경우 처리
            if response is None:
                print("[parse_response] 응답이 None입니다.")
                return None
            
            # 응답이 문자열인 경우 JSON으로 파싱
            if isinstance(response, str):
                try:
                    response = json.loads(response)
                except json.JSONDecodeError:
                    print("[parse_response] JSON 파싱 실패")
                    return None
            
            # 응답이 딕셔너리인 경우 처리
            if isinstance(response, dict):
                print(f"[parse_response] 딕셔너리 응답 처리 중... 키: {list(response.keys())}")
                
                # Claude API 응답 형식에 맞게 처리
                if 'content' in response and isinstance(response['content'], list):
                    content = response['content'][0]
                    if isinstance(content, dict) and 'text' in content:
                        text_data = content['text']
                        
                        # 필수 필드 확인
                        if not all(key in text_data for key in ['english_caption', 'korean_caption']):
                            print("[parse_response] 필수 필드 누락")
                            return None
                        
                        # 스키마에 맞는 결과 반환
                        result = {
                            'text': {
                                'english_caption': text_data['english_caption'],
                                'korean_caption': text_data['korean_caption']
                            }
                        }
                        return result
            
            print(f"[parse_response] 지원되지 않는 응답 형식: {type(response)}")
            return None

        except Exception as e:
            print(f"[parse_response] 응답 파싱 오류: {e}")
            traceback.print_exc()
            return None

    def handle_result(self, file_path, response):
        """API 응답 결과 처리"""
        try:
            file_name = os.path.basename(file_path)
            
            # 응답 검증
            if not response:
                raise ValueError(f"Empty response for {file_name}")
            
            # 응답이 딕셔너리인지 확인
            if not isinstance(response, dict):
                raise ValueError(f"Response is not a dictionary: {type(response)}")
            
            # Claude API 응답 형식에 맞게 필수 필드 확인
            required_fields = ["text"]
            for field in required_fields:
                if field not in response:
                    raise ValueError(f"Missing required field '{field}' in response")
            
            # 처리된 파일 목록에 추가
            self.processed_files.add(file_path)
            
            # 결과 저장
            self.results.append({
                'file_path': file_path,
                'response': response
            })
            
            # 로그 추가
            if self.progress_dialog:
                self.progress_dialog.add_log(f"\n처리 완료: {file_name}")
                formatted_response = self.format_response(response)
                self.progress_dialog.add_log(f"응답:\n{formatted_response}")
            
            self.logger.info(f"Successfully processed {file_name}")
            
            # 메인 UI에 결과 전달 (테이블에서 항목 삭제를 위해)
            if self.main_ui and hasattr(self.main_ui, 'handle_result'):
                self.main_ui.handle_result(file_path, response)
            
        except Exception as e:
            self.logger.error(f"Error handling result for {file_path}: {e}")
            self.error_occurred.emit(f"파일 처리 오류: {str(e)}")
            # 오류가 발생해도 프로그램이 계속 실행되도록 예외를 다시 발생시키지 않음

    def format_response(self, response):
        """응답을 보기 좋게 포맷팅"""
        try:
            # 응답이 딕셔너리인 경우
            if isinstance(response, dict):
                # Claude API 응답 형식에 맞게 처리
                if 'content' in response and isinstance(response['content'], list):
                    content = response['content'][0]
                    if isinstance(content, dict) and 'text' in content:
                        text_data = content['text']
                        formatted_text = (
                            f"영어 캡션: {text_data.get('english_caption', '정보 없음')}\n"
                            f"한글 캡션: {text_data.get('korean_caption', '정보 없음')}"
                        )
                        return formatted_text
                else:
                    # Claude API 응답 형식이 아닌 경우 그대로 반환
                    return json.dumps(response, ensure_ascii=False, indent=2)
            
            # 문자열인 경우 그대로 반환
            return str(response)
            
        except Exception as e:
            self.logger.error(f"Error formatting response: {e}")
            return str(response)

    def handle_error(self, error_msg):
        """에러 처리"""
        if self.progress_dialog:
            self.progress_dialog.add_log(f"오류: {error_msg}")
        self.error_occurred.emit(error_msg)

    def process_complete(self, results=None):
        """처리 완료"""
        # 이미 처리 완료된 경우 중복 실행 방지
        if self.processing_completed:
            print("이미 처리가 완료되었습니다. 중복 호출 무시.")
            return
        
        # 맨 앞에서 처리 완료 상태 설정 (중복 호출 방지)
        self.processing_completed = True
        
        self.logger.info("process_complete 호출됨")
        
        if self.progress_dialog:
            # JSONL 파일 경로 가져오기
            jsonl_file_path = self.worker.jsonl_file_path if self.worker else None
            
            self.progress_dialog.add_log("\n모든 이미지 처리가 완료되었습니다.")
            self.progress_dialog.update_progress(100)

            if jsonl_file_path and os.path.exists(jsonl_file_path):
                self.progress_dialog.add_log(f"\n결과가 JSONL 파일에 저장되었습니다: {jsonl_file_path}")
                
                # 결과 파일 수를 확인하여 로그 추가
                try:
                    with open(jsonl_file_path, 'r', encoding='utf-8') as f:
                        line_count = sum(1 for _ in f)
                    self.progress_dialog.add_log(f"총 {line_count}개의 이미지 처리 결과가 저장되었습니다.")
                except Exception as e:
                    self.logger.error(f"파일 라인 수 확인 오류: {e}")
            else:
                self.progress_dialog.add_log("\n처리 결과 저장에 실패했거나 결과 파일을 찾을 수 없습니다.")

            # 시그널 발생
            self.process_finished.emit()
            
            # 완료 메시지를 다이얼로그에 추가
            self.progress_dialog.add_log("\n처리가 완료되었습니다. 창을 닫으려면 닫기 버튼을 클릭하세요.")
            
            # 취소 버튼 텍스트 변경
            self.progress_dialog.cancel_button.setText("닫기")

    def cancel_processing(self):
        """처리 취소"""
        if self.worker:
            self.worker.stop()
            self.worker.wait()
        self.cleanup()
        self.error_occurred.emit("처리가 취소되었습니다.")

    def cleanup(self):
        """리소스 정리"""
        try:
            if self.worker:
                self.worker.stop()
                self.worker.wait()
                self.worker = None
            
            if self.progress_dialog:
                self.progress_dialog.close()
                self.progress_dialog = None
            
        except Exception as e:
            self.logger.error(f"Error in cleanup: {e}")

    def set_api_key(self, api_key):
        """API 키 설정"""
        self.api_key = api_key
        # Anthropic 클라이언트 초기화 또는 업데이트
        self.client = Anthropic(api_key=api_key)

    def update_progress_incremental(self):
        """진행 상황을 증가시키는 메소드"""
        if not self.progress_dialog:
            print("Progress dialog not found!")
            return
            
        # 이미 처리 완료된 경우는 중복 호출하지 않음
        if self.processing_completed:
            return
            
        # 현재 처리된 항목 수 계산
        processed_count = len(self.processed_files)
        total_count = self.progress_dialog.total_images
        
        # 디버깅을 위한 로그 추가
        print(f"DEBUG - Processed files: {processed_count}/{total_count}")
        print(f"DEBUG - Processed files list: {self.processed_files}")
        
        # 진행률 계산 (0-100%)
        if total_count > 0:
            progress_percentage = min(100, int((processed_count / total_count) * 100))
            print(f"DEBUG - Progress percentage: {progress_percentage}%")
            self.progress_updated.emit(progress_percentage)
            self.progress_dialog.update_progress(progress_percentage)
            
            # 처리 로그 업데이트
            self.progress_dialog.add_log(f"진행 상황: {processed_count}/{total_count} 파일 처리 완료 ({progress_percentage}%)")
        
        # 모든 항목 처리 완료 확인 (이미 완료 상태가 아닌 경우만)
        if not self.processing_completed and processed_count >= total_count:
            print("DEBUG - All files processed, calling process_complete")
            self.process_complete()