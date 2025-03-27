import os
import sys
import time
import json
import traceback
import re
import base64
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal, QSettings
from PyQt5.QtWidgets import QFileDialog
from anthropic import Anthropic
from queue import Queue, Empty
from PyQt5.QtWidgets import QApplication

class WorkerThreadChatCompletion(QThread):
    # WorkerThread와 동일한 시그널 정의
    progress = pyqtSignal(int, int)
    progress_signal = pyqtSignal(int, int)
    result = pyqtSignal(str, str)
    error = pyqtSignal(str)
    finished = pyqtSignal(list)
    current_file = pyqtSignal(str)
    remove_from_table = pyqtSignal(str)
    result_signal = pyqtSignal(str, dict)
    error_signal = pyqtSignal(str, str)
    status_signal = pyqtSignal(str)
    increment_progress_signal = pyqtSignal()
    completed_signal = pyqtSignal(str)

    def __init__(self, queue=None, settings_handler=None, image_processor=None, image_paths=None, api_key=None):
        super().__init__()
        # WorkerThread와 동일한 초기화 로직
        self.queue = queue if queue is not None else Queue()
        self.image_queue = self.queue
        self.settings_handler = settings_handler
        self.image_processor = image_processor
        self.stopped = False
        self.is_paused = False
        self.client = None
        self.api_key = api_key
        self.jsonl_file_path = None
        self.responses = []
        self.is_running = True

        # 마지막 저장 위치 설정
        self.last_save_directory = os.path.expanduser('~')
        if self.settings_handler:
            save_dir = self.settings_handler.get_setting('last_save_directory')
            if save_dir and os.path.exists(save_dir):
                self.last_save_directory = save_dir

        # image_paths가 있으면 큐에 추가
        if image_paths:
            for image_path in image_paths:
                self.queue.put(image_path)

        # API 키 로드
        self.load_api_settings()

    def load_api_settings(self):
        """API 키와 Anthropic 클라이언트 초기화"""
        try:
            # 이미 API 키가 설정되어 있지 않은 경우에만 settings_handler에서 로드
            if not self.api_key and self.settings_handler:
                self.api_key = self.settings_handler.get_setting('claude_key', '')
            
            if not self.api_key:
                self.error_signal.emit("설정 오류", "API 키가 설정되지 않았습니다.")
                return False
            
            # Anthropic 클라이언트 초기화
            self.client = Anthropic(api_key=self.api_key)
            print("Anthropic 클라이언트 초기화 완료")
            return True
        except Exception as e:
            self.error_signal.emit("API 설정 오류", str(e))
            return False

    def request_extract_keyword(self, image_path):
        """Claude API를 사용한 이미지 분석 요청"""
        max_retries = 3
        retry_delay = 2
        
        file_name = os.path.basename(image_path)
        self.status_signal.emit(f"처리 시작: {file_name}")
        print(f"\n=== Processing Image: {file_name} ===")
        
        for attempt in range(max_retries):
            try:
                # 이미지 파일 크기 확인
                file_size = os.path.getsize(image_path)
                print(f"File size: {file_size} bytes")
                size_mb = file_size / (1024*1024)
                self.status_signal.emit(f"{file_name} - 파일 크기: {size_mb:.2f} MB")
                
                # 이미지 파일이 너무 크면 경고 로그 추가
                if file_size > 20 * 1024 * 1024:  # 20MB 이상
                    print(f"경고: 이미지 파일이 매우 큽니다 ({size_mb:.2f} MB). 처리 시간이 오래 걸릴 수 있습니다.")
                    self.status_signal.emit(f"경고: {file_name}의 크기가 매우 큽니다. 처리 시간이 오래 걸릴 수 있습니다.")
                
                # 이미지 파일 준비 및 base64 인코딩
                self.status_signal.emit(f"{file_name} - 이미지 인코딩 중...")
                with open(image_path, "rb") as image_file:
                    # 이미지 데이터를 base64로 인코딩
                    image_data = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Claude API 요청
                self.status_signal.emit(f"{file_name} - 이미지 분석 요청 중...")
                try:
                    # 이미지 분석 요청
                    response = self.client.messages.create(
                        model="claude-3-7-sonnet-20250219",
                        max_tokens=4096,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": """이미지를 분석하여 다음 형식으로 응답해주세요:
{
  "text": {
    "english_caption": "영어로 된 이미지 상세 설명 (3문장). 사람이 있다면 성별, 나이대, 외모 특징, 의상, 표정 등을 포함하여 묘사해주세요.",
    "korean_caption": "한글로 된 이미지 상세 설명 (3문장). 사람이 있다면 성별, 나이대, 외모 특징, 의상, 표정 등을 포함하여 묘사해주세요."
  }
}

주의사항:
1. 사람이 있는 경우 반드시 성별을 명시해주세요 (예: 남성, 여성, 남자, 여자)
2. 나이대도 가능한 경우 포함해주세요 (예: 20대 초반, 30대 중반, 40대 후반 등)
3. 외모 특징, 의상, 표정 등도 상세히 묘사해주세요
4. 사람이 없는 경우에는 이미지의 주요 요소와 분위기를 상세히 묘사해주세요
5. 응답은 반드시 위의 JSON 형식을 지켜주세요"""
                                    },
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/jpeg",
                                            "data": image_data
                                        }
                                    }
                                ]
                            }
                        ]
                    )
                    
                    print(f"Response received: {response}")
                    self.status_signal.emit(f"{file_name} - 응답 수신 완료")
                    
                    # 응답에서 JSON 추출
                    response_text = response.content[0].text
                    response_json = self.extract_json_from_text(response_text, file_name)
                    
                    if response_json:
                        try:
                            self.status_signal.emit(f"{file_name} - 응답 데이터 처리 중...")
                            print(f"API 응답 데이터: {response_json}")
                            
                            # 응답 검증
                            if not response_json.get("text") or \
                               not response_json["text"].get("english_caption") or \
                               not response_json["text"].get("korean_caption"):
                                self.status_signal.emit(f"{file_name} - 필수 필드가 누락됨")
                                print(f"Missing required fields in response: {response_json}")
                                continue
                            
                            print(f"{file_name} - 응답 검증 완료")
                            
                            # 캡션 내용 가져오기
                            text_content = {
                                "english_caption": response_json["text"]["english_caption"].strip(),
                                "korean_caption": response_json["text"]["korean_caption"].strip()
                            }
                            
                            # 문장 수 검증 함수
                            def count_sentences(text):
                                # 영어 문장 구분: .!? 뒤에 공백이나 문장 끝
                                if any(ord(c) < 128 for c in text):  # 영어 텍스트
                                    sentences = [s.strip() for s in re.split(r'[.!?](?=\s|$)', text) if s.strip()]
                                # 한글 문장 구분: .!?。！？ 뒤에 공백이나 문장 끝
                                else:  # 한글 텍스트
                                    sentences = [s.strip() for s in re.split(r'[.!?。！？](?=\s|$)', text) if s.strip()]
                                return sentences
                            
                            print(f"{file_name} - 문장 수 검증 시작")
                            # 캡션 문장 수 검증 및 처리
                            eng_sentences = count_sentences(text_content["english_caption"])
                            kor_sentences = count_sentences(text_content["korean_caption"])
                            
                            if len(eng_sentences) > 3:
                                text_content["english_caption"] = '. '.join(eng_sentences[:3]) + '.'
                                print(f"English caption truncated to 3 sentences")
                                self.status_signal.emit(f"{file_name} - 영어 캡션 3문장으로 조정")
                            
                            if len(kor_sentences) > 3:
                                text_content["korean_caption"] = '. '.join(kor_sentences[:3]) + '.'
                                print(f"Korean caption truncated to 3 sentences")
                                self.status_signal.emit(f"{file_name} - 한글 캡션 3문장으로 조정")
                            
                            # 문장 수가 3개 미만인 경우 로그 출력
                            if len(eng_sentences) < 3 or len(kor_sentences) < 3:
                                print(f"Warning: Caption has fewer than 3 sentences. English: {len(eng_sentences)}, Korean: {len(kor_sentences)}")
                                self.status_signal.emit(f"{file_name} - 경고: 캡션이 3문장 미만입니다")
                            
                            print(f"{file_name} - 문장 수 검증 완료")
                            
                            # 최종 결과 객체 생성
                            formatted_result = {
                                "content": os.path.basename(image_path),
                                "image_path": image_path.replace("\\", "/"),
                                "text": text_content
                            }
                            
                            print(f"처리된 결과: {json.dumps(formatted_result, ensure_ascii=False, indent=2)}")
                            self.status_signal.emit(f"{file_name} - 처리 완료")
                            return formatted_result
                            
                        except json.JSONDecodeError as e:
                            print(f"JSON 파싱 오류: {e}")
                            print(f"원본 응답: {response_json}")
                            self.status_signal.emit(f"{file_name} - JSON 파싱 오류: {e}")
                            continue
                    
                    self.status_signal.emit(f"{file_name} - 응답이 없거나 처리할 수 없는 형식입니다")
                    return None
                    
                except Exception as api_error:
                    print(f"API 요청 오류: {api_error}")
                    self.status_signal.emit(f"{file_name} - API 요청 실패: {str(api_error)}")
                    raise

            except Exception as e:
                error_detail = str(e)
                print(f"Error in request: {error_detail}")
                self.status_signal.emit(f"{file_name} - 오류 발생: {error_detail}")
                
                # 과부하 에러(529) 또는 타임아웃 에러인 경우
                if ("529" in error_detail or "overloaded" in error_detail.lower() or 
                    "timeout" in error_detail.lower()) and attempt < max_retries - 1:
                    # 지수 백오프(exponential backoff) 적용
                    wait_time = retry_delay * (2 ** attempt)  # 2, 4, 8초로 증가
                    retry_msg = f"{file_name} - 서버 과부하 감지. {wait_time}초 후 재시도 중... (Attempt {attempt + 1}/{max_retries})"
                    print(retry_msg)
                    self.status_signal.emit(retry_msg)
                    time.sleep(wait_time)
                    continue
                elif attempt < max_retries - 1:
                    retry_msg = f"{file_name} - 오류 발생. 재시도 중... (Attempt {attempt + 1}/{max_retries})"
                    print(retry_msg)
                    self.status_signal.emit(retry_msg)
                    time.sleep(retry_delay)
                    continue
                
                self.status_signal.emit(f"{file_name} - 최대 재시도 횟수 초과. 처리 실패")
                raise

            finally:
                try:
                    if image_file:
                        image_file.close()
                        print("Image file closed")
                except Exception as close_error:
                    print(f"Error closing file: {close_error}")
                    self.status_signal.emit(f"{file_name} - 파일 닫기 오류: {close_error}")

    def request_extract_keyword_multiple(self, image_paths):
        """여러 이미지를 한 번에 분석하는 요청"""
        max_retries = 3
        retry_delay = 2
        
        if not image_paths:
            self.status_signal.emit("오류: 처리할 이미지가 없습니다.")
            return None
            
        file_names = [os.path.basename(path) for path in image_paths]
        self.status_signal.emit(f"처리 시작: {', '.join(file_names)}")
        print(f"\n=== Processing Multiple Images: {', '.join(file_names)} ===")
        
        for attempt in range(max_retries):
            try:
                # 이미지 데이터 준비
                image_contents = []
                for image_path in image_paths:
                    file_name = os.path.basename(image_path)
                    self.status_signal.emit(f"{file_name} - 이미지 인코딩 중...")
                    
                    with open(image_path, "rb") as image_file:
                        # 이미지 데이터를 base64로 인코딩
                        image_data = base64.b64encode(image_file.read()).decode('utf-8')
                        
                        # MIME 타입 결정
                        mime_type = "image/jpeg"  # 기본값
                        if image_path.lower().endswith('.png'):
                            mime_type = "image/png"
                        elif image_path.lower().endswith('.gif'):
                            mime_type = "image/gif"
                        elif image_path.lower().endswith('.webp'):
                            mime_type = "image/webp"
                        
                        # data URL 형식으로 변환
                        image_url = f"data:{mime_type};base64,{image_data}"
                        image_contents.append({
                            "type": "input_image",
                            "image_url": image_url
                        })
                
                # Responses API 요청
                self.status_signal.emit(f"이미지 분석 요청 중... (총 {len(image_paths)}개)")
                try:
                    response = self.client.messages.create(
                        model="claude-3-7-sonnet-20250219",
                        max_tokens=4096,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "이미지들을 분석하여 다음 JSON 형식으로 응답해주세요: {\"text\": {\"english_caption\": \"영어로 된 이미지 상세 설명(3문장)\", \"korean_caption\": \"한글로 된 이미지 상세 설명(3문장)\"}}"
                                    }
                                ] + image_contents
                            }
                        ]
                    )
                    
                    print(f"Response received: {response}")
                    self.status_signal.emit("응답 수신 완료")
                    
                    # 응답에서 JSON 추출
                    response_text = response.content[0].text
                    response_json = self.extract_json_from_text(response_text, "multiple_images")
                    
                    if response_json:
                        try:
                            self.status_signal.emit("응답 데이터 처리 중...")
                            print(f"API 응답 데이터: {response_json}")
                            
                            # 응답 검증
                            if not response_json.get("text") or \
                               not response_json["text"].get("english_caption") or \
                               not response_json["text"].get("korean_caption"):
                                self.status_signal.emit("필수 필드가 누락됨")
                                print(f"Missing required fields in response: {response_json}")
                                continue
                            
                            print("응답 검증 완료")
                            
                            # 캡션 내용 가져오기
                            text_content = {
                                "english_caption": response_json["text"]["english_caption"].strip(),
                                "korean_caption": response_json["text"]["korean_caption"].strip()
                            }
                            
                            # 문장 수 검증 함수
                            def count_sentences(text):
                                # 영어 문장 구분: .!? 뒤에 공백이나 문장 끝
                                if any(ord(c) < 128 for c in text):  # 영어 텍스트
                                    sentences = [s.strip() for s in re.split(r'[.!?](?=\s|$)', text) if s.strip()]
                                # 한글 문장 구분: .!?。！？ 뒤에 공백이나 문장 끝
                                else:  # 한글 텍스트
                                    sentences = [s.strip() for s in re.split(r'[.!?。！？](?=\s|$)', text) if s.strip()]
                                return sentences
                            
                            print("문장 수 검증 시작")
                            # 캡션 문장 수 검증 및 처리
                            eng_sentences = count_sentences(text_content["english_caption"])
                            kor_sentences = count_sentences(text_content["korean_caption"])
                            
                            if len(eng_sentences) > 3:
                                text_content["english_caption"] = '. '.join(eng_sentences[:3]) + '.'
                                print("English caption truncated to 3 sentences")
                                self.status_signal.emit("영어 캡션 3문장으로 조정")
                            
                            if len(kor_sentences) > 3:
                                text_content["korean_caption"] = '. '.join(kor_sentences[:3]) + '.'
                                print("Korean caption truncated to 3 sentences")
                                self.status_signal.emit("한글 캡션 3문장으로 조정")
                            
                            # 문장 수가 3개 미만인 경우 로그 출력
                            if len(eng_sentences) < 3 or len(kor_sentences) < 3:
                                print(f"Warning: Caption has fewer than 3 sentences. English: {len(eng_sentences)}, Korean: {len(kor_sentences)}")
                                self.status_signal.emit("경고: 캡션이 3문장 미만입니다")
                            
                            print("문장 수 검증 완료")
                            
                            # 각 이미지별 결과 생성
                            results = []
                            for image_path in image_paths:
                                formatted_result = {
                                    "content": os.path.basename(image_path),
                                    "image_path": image_path.replace("\\", "/"),
                                    "text": text_content.copy()  # 각 이미지별로 동일한 텍스트 복사
                                }
                                results.append(formatted_result)
                            
                            print(f"처리된 결과: {json.dumps(results, ensure_ascii=False, indent=2)}")
                            self.status_signal.emit("처리 완료")
                            return results
                            
                        except json.JSONDecodeError as e:
                            print(f"JSON 파싱 오류: {e}")
                            print(f"원본 응답: {response_json}")
                            self.status_signal.emit(f"JSON 파싱 오류: {e}")
                            continue
                    
                    self.status_signal.emit("응답이 없거나 처리할 수 없는 형식입니다")
                    return None
                    
                except Exception as api_error:
                    print(f"API 요청 오류: {api_error}")
                    self.status_signal.emit(f"API 요청 실패: {str(api_error)}")
                    raise

            except Exception as e:
                error_detail = str(e)
                print(f"Error in request: {error_detail}")
                self.status_signal.emit(f"오류 발생: {error_detail}")
                
                # 과부하 에러(529) 또는 타임아웃 에러인 경우
                if ("529" in error_detail or "overloaded" in error_detail.lower() or 
                    "timeout" in error_detail.lower()) and attempt < max_retries - 1:
                    # 지수 백오프(exponential backoff) 적용
                    wait_time = retry_delay * (2 ** attempt)  # 2, 4, 8초로 증가
                    retry_msg = f"타임아웃 오류 감지. {wait_time}초 후 재시도 중... (Attempt {attempt + 1}/{max_retries})"
                    print(retry_msg)
                    self.status_signal.emit(retry_msg)
                    time.sleep(wait_time)
                    continue
                elif attempt < max_retries - 1:
                    retry_msg = f"오류 발생. 재시도 중... (Attempt {attempt + 1}/{max_retries})"
                    print(retry_msg)
                    self.status_signal.emit(retry_msg)
                    time.sleep(retry_delay)
                    continue
                
                self.status_signal.emit("최대 재시도 횟수 초과. 처리 실패")
                raise

    def stop(self):
        """스레드 중지"""
        self.stopped = True
        self.is_running = False
        print("Worker thread stopping...")
        self.status_signal.emit("작업 중지 중...") 

    def initialize_jsonl_file(self):
        """JSONL 파일 초기화 - 사용자가 파일 위치 선택 가능"""
        try:
            # 타임스탬프를 이용한 기본 파일명 생성
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            default_filename = f"captions_{timestamp}.jsonl"
            
            # 파일 저장 다이얼로그 표시
            file_path, _ = QFileDialog.getSaveFileName(
                None,  # 부모 위젯 없음
                "JSONL 파일 저장 위치 선택",
                os.path.join(self.last_save_directory, default_filename),
                "JSONL Files (*.jsonl);;All Files (*)"
            )
            
            # 사용자가 취소한 경우
            if not file_path:
                print("사용자가 파일 저장을 취소했습니다. 기본 위치에 저장합니다.")
                self.jsonl_file_path = os.path.join(self.last_save_directory, default_filename)
            else:
                # 확장자 확인 및 추가
                if not file_path.lower().endswith('.jsonl'):
                    file_path += '.jsonl'
                    print(f"확장자 .jsonl 추가: {file_path}")
                
                self.jsonl_file_path = file_path
                
                # 선택된 디렉토리 저장
                save_directory = os.path.dirname(file_path)
                if self.settings_handler:
                    self.settings_handler.save_setting('last_save_directory', save_directory)
                    self.last_save_directory = save_directory
                    print(f"저장 위치 업데이트: {save_directory}")
            
            # 빈 JSONL 파일 생성
            with open(self.jsonl_file_path, 'w', encoding='utf-8') as f:
                pass  # 빈 파일 생성
            
            # 상태 메시지 표시
            print(f"JSONL 파일 초기화 완료: {self.jsonl_file_path}")
            self.status_signal.emit(f"JSONL 파일 생성 완료: {self.jsonl_file_path}")
            
            return True
        except Exception as e:
            print(f"JSONL 파일 초기화 오류: {e}")
            traceback.print_exc()
            self.error_signal.emit("파일 오류", f"JSONL 파일 초기화 실패: {e}")
            
            # 오류 발생 시 기본 경로에 저장
            try:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                default_filename = f"captions_{timestamp}.jsonl"
                self.jsonl_file_path = os.path.join(os.path.expanduser('~'), default_filename)
                with open(self.jsonl_file_path, 'w', encoding='utf-8') as f:
                    pass
                print(f"오류 발생으로 기본 위치에 파일 생성: {self.jsonl_file_path}")
                return True
            except:
                return False

    def append_to_jsonl(self, result):
        """결과를 JSONL 파일에 추가"""
        try:
            with open(self.jsonl_file_path, 'a', encoding='utf-8') as f:
                json_line = json.dumps(result, ensure_ascii=False)
                f.write(json_line + '\n')
            print(f"결과가 JSONL 파일에 추가됨: {os.path.basename(result.get('image_path', 'unknown'))}")
            return True
        except Exception as e:
            print(f"JSONL 파일 기록 오류: {e}")
            self.error_signal.emit("파일 오류", f"JSONL 파일 기록 실패: {e}")
            return False

    def extract_json_from_text(self, text, file_name):
        """텍스트에서 JSON 데이터 추출"""
        if not text:
            return None
            
        # 디버깅을 위한 응답 내용 출력
        print(f"응답 텍스트: {text[:200]}..." if len(text) > 200 else text)
        self.status_signal.emit(f"{file_name} - 응답 데이터 수신 완료")
        
        try:
            # 1. 마크다운 코드 블록 내 JSON 추출 시도
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
            if json_match:
                json_str = json_match.group(1).strip()
                try:
                    json_obj = json.loads(json_str)
                    self.status_signal.emit(f"{file_name} - JSON 형식 응답 발견 (코드 블록)")
                    return json_obj
                except:
                    pass  # 파싱 실패하면 다음 방법 시도
            
            # 2. 중괄호로 둘러싸인 JSON 객체 추출 시도
            json_pattern = r'(\{(?:[^{}]|(?:\{(?:[^{}]|(?:\{[^{}]*\}))*\}))*\})'
            json_match = re.search(json_pattern, text)
            if json_match:
                json_str = json_match.group(1).strip()
                try:
                    json_obj = json.loads(json_str)
                    self.status_signal.emit(f"{file_name} - JSON 객체 발견")
                    return json_obj
                except:
                    pass  # 파싱 실패하면 다음 방법 시도
            
            # 3. 전체 텍스트가 JSON인지 확인
            try:
                json_obj = json.loads(text)
                self.status_signal.emit(f"{file_name} - 유효한 JSON 응답 수신")
                return json_obj
            except:
                # 파싱에 실패하면 원본 텍스트 반환
                self.status_signal.emit(f"{file_name} - JSON 파싱 실패, 텍스트 응답으로 처리")
                return text
                
        except Exception as e:
            print(f"JSON 추출 오류: {e}")
            self.status_signal.emit(f"{file_name} - JSON 추출 실패: {e}")
            return text  # 오류 발생시 원본 텍스트 반환

    def run(self):
        """스레드 실행"""
        if not self.image_queue or self.image_queue.empty():
            self.emit_status_signal("오류: 처리할 이미지가 없습니다.")
            self.emit_status_signal("처리 완료")
            return
            
        try:
            # JSONL 파일 초기화
            self.initialize_jsonl_file()
            
            # Anthropic API 설정 로드
            self.emit_status_signal("Anthropic API 설정 로드 중...")
            
            # API 키 확인
            if not self.api_key:
                self.emit_status_signal("오류: API 키가 설정되지 않았습니다.")
                return
                
            # 이미지 처리 시작
            total_images = self.image_queue.qsize()
            processed_count = 0
            
            self.emit_status_signal(f"이미지 처리 시작 (총 {total_images}개)...")
            
            while not self.image_queue.empty():
                # 취소 요청 확인
                if self.stopped:
                    # 결과 파일 경로 알림
                    msg = f"작업이 취소되었습니다. 결과 파일: {self.jsonl_file_path}"
                    self.emit_status_signal(msg)
                    self.completed_signal.emit(msg)
                    break
                    
                # 일시정지 요청 확인
                if self.is_paused:
                    self.emit_status_signal("처리가 일시정지되었습니다. 재개하려면 '재개' 버튼을 클릭하세요.")
                    while self.is_paused and not self.stopped:
                        QThread.msleep(500)
                    
                    if not self.is_paused:
                        self.emit_status_signal("처리가 재개되었습니다.")
                    
                    if self.stopped:
                        msg = f"작업이 취소되었습니다. 결과 파일: {self.jsonl_file_path}"
                        self.emit_status_signal(msg)
                        self.completed_signal.emit(msg)
                        break
                
                # 이미지 추출
                image_path = self.image_queue.get()
                file_name = os.path.basename(image_path)
                
                self.current_file.emit(file_name)
                self.emit_status_signal(f"처리 중: {file_name}")
                
                try:
                    # 이미지 처리
                    result = self.request_extract_keyword(image_path)
                    
                    if result and 'content' in result:
                        # 결과 저장
                        self.append_to_jsonl(result)
                        processed_count += 1
                        self.emit_status_signal(f"처리 완료: {file_name}")
                        self.result_signal.emit(image_path, result)
                    else:
                        self.emit_status_signal(f"처리 실패: {file_name} (결과 없음)")
                except Exception as e:
                    self.emit_status_signal(f"이미지 처리 오류: {file_name} - {str(e)}")
                
                # 진행 상황 업데이트
                self.progress.emit(processed_count, total_images)
            
            # 취소되지 않았을 경우 완료 메시지 표시
            if not self.stopped:
                msg = f"모든 이미지 처리가 완료되었습니다. 결과 파일: {self.jsonl_file_path}"
                self.emit_status_signal(msg)
                self.completed_signal.emit(msg)
        
        except Exception as e:
            error_msg = f"처리 오류: {str(e)}"
            self.emit_status_signal(error_msg)
            traceback.print_exc()

    def emit_status_signal(self, message):
        """상태 메시지를 전송하는 편의 메서드"""
        try:
            self.status_signal.emit(message)
        except Exception as e:
            print(f"상태 메시지 전송 오류: {e}")

    def pause(self):
        """작업 일시 정지"""
        self.is_paused = True
        self.status_signal.emit("작업이 일시 정지되었습니다.")
    
    def resume(self):
        """작업 재개"""
        self.is_paused = False
        self.status_signal.emit("작업이 재개되었습니다.")
    
    def cancel(self):
        """작업 취소"""
        self.stopped = True
        self.status_signal.emit("작업 취소 요청이 접수되었습니다.")
        
        # 작업 큐를 비워 추가 처리 방지
        while not self.image_queue.empty():
            try:
                self.image_queue.get(block=False)
            except Empty:
                break
                
        self.status_signal.emit("모든 작업이 취소되었습니다.")

    def add_image(self, image_path):
        """이미지 경로를 큐에 추가"""
        try:
            # 상대 경로를 절대 경로로 변환
            abs_path = os.path.abspath(image_path)
            
            # 파일 존재 여부 확인
            if not os.path.exists(abs_path):
                print(f"경고: 파일이 존재하지 않습니다: {abs_path}")
                self.error_signal.emit("파일 오류", f"파일이 존재하지 않습니다: {image_path}")
                return False
            
            self.image_queue.put(abs_path)
            return True
        except Exception as e:
            print(f"이미지 추가 오류: {str(e)}")
            return False 