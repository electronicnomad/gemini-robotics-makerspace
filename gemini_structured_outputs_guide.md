# Gemini Structured Outputs 연동 가이드 (google-genai SDK v2.10)

본 가이드는 현재 `robot_puppy_core.py`에 적용된 **일반 텍스트 프롬프트 기반 JSON 파싱** 방식을, Gemini API가 제공하는 강력하고 안전한 **Structured Outputs(구조화된 출력)** 방식으로 고도화하는 설계서 및 구체적인 리팩토링 방안을 제공합니다.

---

## 1. 기존 파싱 방식 vs Structured Outputs 비교

| 항목 | 기존 방식 (텍스트 프롬프트 + 정규식 파싱) | Structured Outputs (Pydantic 스키마 가이드) |
| :--- | :--- | :--- |
| **작동 원리** | 프롬프트 내에 JSON 예시를 주고 모델이 이를 잘 생성하기를 기대함 | API 레벨에서 강제로 JSON Schema 규칙을 삽입하여 출력을 제한함 |
| **출력 신뢰도** | 가끔 백틱(```json)이 붙거나 주석, 마침표 등으로 인해 파싱 실패 위험 | 모델이 항상 정의된 스키마 구조에 완벽히 부합하는 JSON만 출력함 |
| **파싱 코드 부하** | 정규식 매칭, `{}` 브레이스 인덱스 검색, 자료형 수동 변환 등 장황함 | `response.parsed` 프로퍼티를 통해 곧바로 Pydantic 객체 획득 |
| **타입 안정성** | `Optional` 필드 누락, 정수형 좌표가 실수형(0.0~1.0)으로 변하는 에러 발생 가능 | Pydantic 데코레이터가 타입 검증 및 디폴트 값 바인딩을 보장 |

---

## 2. google-genai SDK에서의 Structured Outputs 구현

`google-genai==2.10.0` 버전에서는 Python의 **Pydantic** 라이브러리를 활용해 원하는 출력 구조를 파이썬 클래스로 정의한 뒤, `response_schema` 옵션에 전달하면 자동으로 활성화됩니다.

### 1) Pydantic 모델 정의
로봇이 사물을 식별하고 생각을 반환하는 구조를 나타내는 Pydantic 스키마 설계입니다.

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class DetectedObject(BaseModel):
    """주변 탐지 사물의 정보와 바운딩 박스를 담는 스키마"""
    box_2d: List[int] = Field(
        ..., 
        description="Normalized coordinates [ymin, xmin, ymax, xmax] on a 0 to 1000 integer scale."
    )
    label: str = Field(
        ..., 
        description="The clear name or label of the detected object (e.g., 'toy', 'food bowl', 'cup')."
    )

class PuppyBrainResponse(BaseModel):
    """Gemini가 최종 반환해야 하는 마스터 응답 스키마"""
    owner_box: Optional[List[int]] = Field(
        None, 
        description="Bounding box [ymin, xmin, ymax, xmax] of the owner, or null/None if not spotted."
    )
    detected_objects: List[DetectedObject] = Field(
        default_factory=list, 
        description="List of up to 8 other detected objects in the environment."
    )
    thought: str = Field(
        ..., 
        description="A brief English thought explaining what you see and how you feel as a robotic puppy."
    )
```

### 2) GenerateContentConfig를 통한 API 연동
`types.GenerateContentConfig` 옵션을 사용해 MIME 타입을 `application/json`으로 명시하고 Pydantic 클래스를 `response_schema`에 할당합니다.

```python
from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# API 호출 구성
config = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=PuppyBrainResponse,
    temperature=0.3, # 결정론적이고 안정적인 바운딩 박스 출력을 위해 낮춤
)

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents=[
        types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
        "You are the robotic puppy's brain. Analyze the frame."
    ],
    config=config
)

# 파싱된 결과 직접 사용하기 (Pydantic 인스턴스로 자동 매핑됨)
brain_data: PuppyBrainResponse = response.parsed

print(f"Thought: {brain_data.thought}")
print(f"Owner Box: {brain_data.owner_box}")
for obj in brain_data.detected_objects:
    print(f"Object: {obj.label} at {obj.box_2d}")
```

---

## 3. `robot_puppy_core.py` 리팩토링 가이드 (Diff)

다음은 실제 프로젝트 파일인 `robot_puppy_core.py` 내의 `gemini_brain_thread` 함수에 적용할 수 있는 구체적인 코드 비교(Diff)입니다.

### 1단계: 임포트 및 Pydantic 클래스 추가
```diff
  from google import genai
  from google.genai import types
+ from pydantic import BaseModel, Field
+ from typing import List, Optional
+ 
+ class DetectedObject(BaseModel):
+     box_2d: List[int] = Field(..., description="Normalized coordinates [ymin, xmin, ymax, xmax] on a 0 to 1000 integer scale.")
+     label: str = Field(..., description="The label of the detected object.")
+ 
+ class PuppyBrainResponse(BaseModel):
+     owner_box: Optional[List[int]] = Field(None, description="[ymin, xmin, ymax, xmax] of the owner, or null/None if not spotted.")
+     detected_objects: List[DetectedObject] = Field(default_factory=list, description="Up to 8 other detected objects.")
+     thought: str = Field(..., description="A brief English thought explaining what you see and feel as a robotic puppy.")
```

### 2단계: `gemini_brain_thread` 내 프롬프트 단순화 및 API 설정 변경
구조적인 데이터 제어가 스키마로 이관되므로, 프롬프트에서 좌표 규칙이나 JSON 구조 문자열 가이드를 장황하게 설명할 필요가 없어집니다.

```diff
-    prompt = f"""
-    You are the robotic puppy's brain. Based on the camera image:
-    1. Locate the target owner... (이하 장황한 규칙 설명)
-    Return ONLY the raw JSON block without markdown formatting or backticks.
-    """
+    prompt = f"You are the robotic puppy's brain. Analyze the image to track the owner ({OWNER_DESCRIPTION}), find notable toys/food objects, and output your inner puppy thought."
```

### 3단계: API 호출 루프 및 후처리 단순화
정규식 검색과 복잡한 타입 파싱 구문이 생략되어 코드 가독성이 비약적으로 대폭 향상됩니다.

```diff
                     model_name = 'gemini-robotics-er-1.6-preview'
+                    config_obj = types.GenerateContentConfig(
+                        response_mime_type="application/json",
+                        response_schema=PuppyBrainResponse,
+                        temperature=0.3
+                    )
                     try:
                         response = client.models.generate_content(
                             model=model_name,
                             contents=[
                                 types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                 prompt
-                            ]
+                            ],
+                            config=config_obj
                         )
                     except Exception as e_model:
                         print(f"[CORTEX] Model '{model_name}' failed... Falling back to 'gemini-2.5-flash'...")
                         model_name = 'gemini-2.5-flash'
                         response = client.models.generate_content(
                             model=model_name,
                             contents=[
                                 types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                                 prompt
-                            ]
+                            ],
+                            config=config_obj
                         )
                     
-                    result_text = response.text.strip()
-                    if result_text.startswith("```"):
-                        # ... (기존의 불안정했던 문자열 자르기 및 예외 파싱 코드들) ...
-                    data = json.loads(result_text.strip())
-                    
-                    # 1. Update multi-object data first... (기존 정수형 변환 연산 생략 가능)
+                    # Structured Output 적용으로 곧바로 안전하게 데이터 접근 가능!
+                    brain_data: PuppyBrainResponse = response.parsed
+                    
+                    valid_objects = []
+                    for obj in brain_data.detected_objects:
+                        valid_objects.append({
+                            "box_2d": obj.box_2d,
+                            "label": obj.label
+                        })
+                    DETECTED_OBJECTS = valid_objects
+                    LAST_DETECTION_TIME = time.time()
+                    
+                    validated_box = brain_data.owner_box
+                    # Fallback: 만약 주인이 스포팅되지 않았는데 객체 목록에 person이 있다면 자동 융합
+                    if validated_box is None:
+                        for obj in valid_objects:
+                            if any(p in obj["label"].lower() for p in ["person", "man", "woman", "owner"]):
+                                validated_box = obj["box_2d"]
+                                break
                     
                     with state_lock:
                         GEMINI_STATUS = "ACTIVE"
                         if CURRENT_STATE == "GAZING" and snapshot_time < gaze_start_time:
                             print("[CORTEX] Discarding stale pre-gaze API response.")
                         else:
-                            LATEST_BBOX = validated_box
+                            LATEST_BBOX = validated_box
                     
-                    LAST_THOUGHT = data.get("thought", "Monitoring environment...")
+                    LAST_THOUGHT = brain_data.thought
```

---

## 4. 연동에 따른 효과

1. **에러 복구 극대화**: API 응답이 정해진 형식을 조금이라도 엇나가는 상황을 완벽하게 차단합니다.
2. **개발 생산성**: 복잡한 정규식 전처리 코드를 삭제하여 유지보수 비용이 대폭 절감됩니다.
3. **프롬프트 토큰 절약**: "JSON 형식을 맞춰라", "마침표나 주석을 넣지 마라", "정수로 반환해라" 등 포맷 통제를 위해 낭비되던 약 100~200 토큰가량의 지시 프롬프트를 획기적으로 절약할 수 있어 비용과 성능 측면 모두에서 매우 유리해집니다.
