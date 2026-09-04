# faraday-cv

패러데이 법칙 진자 실험용 **컬러 세그멘테이션 영상 분석 도구**.

진자 자석 영상에서 색으로 자석을 추적해 **위치·순간속도**를 뽑고, 따로 올린
**아두이노 전압 로그**를 LED 타이밍 신호로 동기화해서, 하나의 시간축 위에
논문용 그래프를 그립니다.

**영상 추적은 브라우저 안에서** 일어납니다 (컬러 세그멘테이션을 JS로 재구현).
서버는 그 결과(좌표 몇 개)와 전압 로그를 받아 물리량을 계산하고 그래프만
그립니다 — 영상 자체는 어디로도 업로드되지 않습니다. 그래서 이 서버는
가벼운 무료 티어(Render, Fly.io 등)에 그대로 올려 여러 사람이 같이 쓸 수
있습니다. 자기 컴퓨터에서만 쓸 거라면 그냥 로컬에서 실행해도 됩니다.

> 관련 논문: _Beyond "Faster Magnet, More Voltage": A Quantitative Faraday's Law
> Experiment Using Computer Vision_ — 코일을 최하점이 아니라 **회전점(turning
> point) 근처**에 두면 최대 속도 지점과 최대 유도전압 지점이 분리되고,
> "빠를수록 전압이 크다"는 규칙이 깨지는 것을 학생이 자기 데이터로 확인합니다.

---

## 무엇이 나오나

| 산출물                        | 내용                                                                        |
| ----------------------------- | --------------------------------------------------------------------------- |
| `fig2_motion_and_voltage.png` | 코일-자석 거리 / 속도 / 유도전압을 같은 시간축에 (논문 Fig. 2)              |
| `fig3_emf_over_velocity.png`  | ℰ 와 ℰ/v 비교 — ℰ/v ∝ −N dΦ/dx (논문 Fig. 3, Eq. 3)                         |
| `diagnostics.png`             | 추적 품질 점검: 중심좌표, 덩어리 면적, LED 신호와 문턱값                    |
| `synced.csv`                  | 동기화된 표: `t, voltage, speed, distance, emf_over_v` — 엑셀로 재분석 가능 |
| `motion.csv`, `track.csv`     | 물리단위 운동 / 프레임별 원시 추적값                                        |
| `summary.json`                | 두 정점의 시각과 값, 검출률, 사용한 설정 전부                               |

---

## 웹으로 바로 쓰기

누군가 이미 배포해 둔 주소가 있다면 그냥 브라우저로 열면 됩니다. 설치할 것도
없고, 영상은 그 사람의 서버로도 전송되지 않습니다 (브라우저 안에서만 처리).

직접 배포하려면 [배포](#배포-웹-서비스로-올리기) 절을 보세요.

## 로컬에서 웹 UI 실행

가상환경을 만들어 설치하는 것을 권합니다 (macOS 기본 파이썬에서 `pip install`이
`externally-managed-environment` 오류를 내는 것을 피할 수 있습니다).

```bash
cd faraday-cv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m faradaycv serve
```

- 두 번째 실행부터는 `source .venv/bin/activate` 후 마지막 줄만 하면 됩니다.
- Windows는 `python3` 대신 `py`, 활성화는 `.venv\Scripts\activate`.
- macOS·Linux에 `pip` 명령이 없어도 됩니다. 항상 `python3 -m pip` 를 쓰세요.
- 아래 명령들은 **`faraday-cv` 폴더 안에서** 실행합니다.
  `No module named faradaycv` 오류는 대부분 다른 폴더에 있다는 뜻입니다.

터미널에 뜨는 주소(기본 `http://127.0.0.1:8000`)를 브라우저에서 열고, 끌 때는
터미널에서 `Ctrl+C`. 포트가 이미 쓰이면 `--port 8080` 처럼 바꾸세요.

브라우저에서 순서대로:

1. **영상 선택** — mp4/mov/webm 등. **업로드가 아닙니다**: 이 컴퓨터에서 바로
   재생·분석하므로 용량 제한이 없고 영상은 이 브라우저를 벗어나지 않습니다
2. **자석 클릭** → HSV 범위 자동 설정, 슬라이더로 미세조정
   (초록색으로 칠해진 부분이 "자석으로 인식된 픽셀")
3. **코일 위치 클릭**, **길이 보정 드래그**(아는 길이를 mm로 입력),
   **LED 영역 드래그**, 촬영한 카메라의 **fps** 확인
4. **아두이노 전압 파일 선택** — 영상과 별개로 따로 선택합니다
5. **추적 + 분석 실행** → 브라우저가 영상을 끝까지 훑어 좌표를 뽑고(진행률
   표시), 그 결과만 서버로 보내 그래프 2장 + 진단 그래프, CSV 다운로드

세그멘테이션이 잘 안 될 때는 ⑤ **검색 영역**을 드래그해 자석이 지나가는
구역만 남기면 배경의 비슷한 색을 무시할 수 있습니다.

## 1분 체험 (장비 없이)

명령줄용 합성 데이터셋(영상 + 전압 로그 + 정답값)을 만들어서 CLI 흐름을
그대로 돌려봅니다. 첫 명령이 `example-data/pendulum.mp4` 와 `voltage.csv` 를
만듭니다. (이 둘을 웹 UI에 그대로 올려도 됩니다.)

```bash
python3 -m faradaycv.synthetic example-data
python3 -m faradaycv analyze example-data/pendulum.mp4 \
    --voltage example-data/voltage.csv \
    --hsv 170,10,120,255,80,255 \
    --led-roi 16,16,34,34 \
    --mm-per-px 2.0833 --coil 397,332 \
    -o example-data/out
```

출력 예시:

```
LED onset       : frame 6 -> t0 = 0.200 s
max speed       : 0.677 m/s at t = 1.724 s
max |emf|       : 20.61 mV at t = 1.534 s
peak separation : -0.190 s (speed at the emf peak: 0.453 m/s)
```

최대 속도 시각과 최대 전압 시각이 **0.19초 어긋나 있고**, 전압이 최대인 순간의
속도는 최대 속도의 67 %, 반대로 속도가 최대일 때 전압은 정점의 7 %밖에 안 됩니다.
논문이 말하는 바로 그 결과입니다.

> 스윙이 여러 번 들어간 기록에서는 최대 속도 지점이 여러 개라서, 비교에 쓰는
> "최대 속도 시각"은 **전압 정점에 가장 가까운** 최대 속도 지점으로 잡습니다.

## 배포 (웹 서비스로 올리기)

서버는 영상을 다루지 않으므로 (numpy/scipy/matplotlib/flask 뿐, OpenCV·ffmpeg
없음) 아주 작은 인스턴스로 충분합니다.

**Render** — 이 저장소를 GitHub에 두고, Render에서 "New +" → "Blueprint" →
이 저장소 선택. **저장소 루트**의 `render.yaml`(이 `faraday-cv/` 폴더 밖,
`general-use/render.yaml`)을 Render가 자동으로 인식하고, 그 안의 `rootDir`
설정이 실제 빌드는 `faraday-cv/` 안에서 하도록 지정합니다. 무료 플랜으로
충분합니다.

> Render가 `render.yaml`을 못 찾고 Dockerfile을 찾다 실패하면("open
> Dockerfile: no such file or directory"), Blueprint가 아니라 "New +" →
> "Web Service"로 직접 만든 경우일 수 있습니다. 그럴 땐 서비스 설정에서
> **Root Directory**를 `faraday-cv`로, **Runtime/Environment**를 `Python 3`
> 으로, **Build Command**를 `pip install -r requirements-web.txt`, **Start
> Command**를 `gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60 wsgi:app`
> 로 직접 지정하세요.

**Fly.io**:

```bash
cd faraday-cv
fly launch   # Dockerfile과 fly.toml을 찾아 그대로 씁니다
fly deploy
```

**Docker (직접 아무 곳에나)**:

```bash
cd faraday-cv
docker build -t faraday-cv .
docker run -p 8000:8000 faraday-cv
```

세 방법 모두 `FARADAYCV_LOCAL_MODE=0` 이 설정됩니다 — 서버가 영상을 대신
디코딩해 주는 기능(로컬 전용, 아래 [영상 형식](#영상-형식) 참고)이 꺼지고,
브라우저 추적 화면만 나옵니다. 다른 환경변수:

| 환경변수                        | 뜻                                                    | 기본값          |
| ------------------------------- | ----------------------------------------------------- | --------------- |
| `FARADAYCV_LOCAL_MODE`          | `0`이면 공개 배포 모드 (서버 영상 처리 기능 비활성화) | `1` (로컬)      |
| `FARADAYCV_SESSION_TTL_MINUTES` | 실행 결과(그래프·CSV) 보관 시간. 지나면 자동 삭제     | `1440` (24시간) |

작은 무료 인스턴스에 여러 사람이 몰릴 수 있으니 `FARADAYCV_SESSION_TTL_MINUTES`
를 60 정도로 짧게 두는 것을 권합니다 (`render.yaml`/`fly.toml`에 이미 반영).

## 명령줄 (CLI, 로컬 전용)

CLI는 **서버가 아니라 OpenCV로 직접 영상을 디코딩**합니다 — 웹 UI의
브라우저 추적과는 별개의, 스크립팅·일괄 처리용 경로입니다.

```bash
python3 -m faradaycv info swing.mp4
python3 -m faradaycv frame swing.mp4 --index 0 --out f.png
python3 -m faradaycv pick swing.mp4 --at 320,180
python3 -m faradaycv track swing.mp4 --hsv 170,10,120,255,80,255 -o track.csv
python3 -m faradaycv analyze swing.mp4 --voltage log.csv --hsv ... -o out/
python3 -m faradaycv serve
```

| 명령      | 하는 일                                    |
| --------- | ------------------------------------------ |
| `info`    | fps, 프레임 수, 해상도                     |
| `doctor`  | 안 열리는 영상의 원인 진단                 |
| `frame`   | 한 프레임을 이미지로 저장 (색 좌표 찾기용) |
| `pick`    | 지정한 픽셀에서 HSV 범위 추정              |
| `track`   | 프레임별 중심좌표 CSV                      |
| `analyze` | 전체 분석: 그래프 + 표 + 요약              |
| `serve`   | 웹 UI                                      |

`analyze` 주요 옵션:

| 옵션                                                            | 뜻                                                          |
| --------------------------------------------------------------- | ----------------------------------------------------------- |
| `--hsv h_lo,h_hi,s_lo,s_hi,v_lo,v_hi`                           | 색 범위 (OpenCV HSV, 색상 0–179). `h_lo > h_hi`면 빨강 순환 |
| `--roi x,y,w,h`                                                 | 검색 영역 제한                                              |
| `--min-area`, `--blur`, `--open`, `--close`                     | 마스크 정리 파라미터                                        |
| `--led-roi x,y,w,h`                                             | LED 동기화 영역 (없으면 `--t0-video`로 수동 지정)           |
| `--mm-per-px` 또는 `--scale-line x0,y0,x1,y1 --scale-length mm` | 길이 보정                                                   |
| `--coil x,y`                                                    | 코일 중심 (거리 그래프에 필요)                              |
| `--smooth`                                                      | Savitzky–Golay 창 크기(프레임). 속도 미분 전 위치 평활화    |
| `--v-min`                                                       | 이 속도 미만에서는 ℰ/v를 그리지 않음 (0으로 나누기 방지)    |

## 아두이노

`arduino/faraday_logger/faraday_logger.ino` 를 업로드하세요.

- **ADS1115** 16비트 ADC (I2C: A4/A5), 코일은 AIN0–AIN1 **차동 입력**
  → 유도전압의 부호가 보존됩니다
- 게인 `GAIN_SIXTEEN`(±0.256 V, 7.8 µV/LSB), 데이터레이트 128 SPS
  → 실측 **약 116 Hz**. ±256 mV에서 잘리면 `GAIN_EIGHT`로 낮추세요
- **D9의 LED**가 동기화 신호입니다. 스케치가 LED를 켜는 순간이 전압 로그의
  t = 0, 영상에서 **LED가 처음 켜져 보이는 프레임**이 영상의 t = 0
  → LED는 반드시 카메라 화면 안에 들어와야 합니다
- 출력은 `t_ms,voltage_mV` CSV. PC에서 저장:

```bash
python3 -m pip install pyserial
python3 tools/serial_logger.py --list
python3 tools/serial_logger.py --port /dev/ttyACM0 --out voltage.csv --seconds 20
```

`--list` 가 포트 목록을 보여줍니다. macOS는 보통 `/dev/tty.usbmodem…` 입니다.

시리얼 모니터 내용을 그대로 복사해 저장해도 됩니다. 다른 스케치·다른 로거로
받은 파일도 그대로 넣으면 됩니다 — 실제 실험 로그에서 확인한 것들:

- `#` 주석, **헤더 없음**, 쉼표/세미콜론/탭/공백 구분자
- 시간 단위 ms·µs·s, 전압 단위 mV·V **자동 판별** (`--voltage-unit`으로 강제 가능).
  헤더가 없으면 ① ADS1115 최대 입력 ±6.144 V를 넘는 값이면 mV, ② 값들이
  ADS1115 LSB(예: GAIN_FOUR = 0.03125 mV) 배수로 떨어지면 mV로 판정합니다.
  판정 결과는 실행 로그와 웹 UI에 항상 표시되니 확인하세요.
- **쓰지 않는 빈 열**(`t,v,0,0,0,…`)은 무시
- **시간이 어긋난 행**(이전 실행에서 남은 첫 줄, 마지막 값이 여러 번 반복된 꼬리)은
  정렬하지 않고 **버립니다**. 정렬해 넣으면 기록 길이가 늘어나고 없는 공백이
  생기기 때문입니다. 몇 행을 버렸는지 결과에 표시됩니다.

## 영상 형식

**웹 UI**는 브라우저가 재생할 수 있는 형식이면 뭐든 됩니다 — 요즘 크롬·엣지·
사파리는 대부분 mp4(H.264/HEVC), webm(VP9/AV1)을 재생합니다. 브라우저가 못 여는
파일이면 화면에 바로 오류가 뜨고, `ffmpeg -i 원본.mp4 -c:v libx264 -pix_fmt
yuv420p -an swing.mp4` 로 재인코딩하면 대부분 해결됩니다.

**CLI**(로컬, OpenCV 기반)는 이보다 관대합니다 — mp4·mov·avi·mkv 등을 그대로
넣으면 되고, OpenCV가 못 읽는 코덱(아이폰 HEVC 등)은 같이 설치된 ffmpeg로
**H.264 고정 프레임레이트 사본을 자동 생성**해서 분석합니다 (`doctor` 명령으로
원인 진단, 자세한 내용은 이전 버전 기록 참고). 이 자동 변환은 **로컬 서버
모드(`local_mode`)의 CLI/구버전 웹 경로에만 있고, 공개 배포한 웹 UI(브라우저
추적)에는 없습니다** — 영상이 서버로 가지 않으니 서버가 대신 변환해 줄 수도
없습니다.

영상이 안 열리면 **원인부터 확인**하세요:

```bash
python3 -m faradaycv doctor /경로/swing.mp4
```

`moov atom is missing` 이 나오면 코덱이 아니라 **파일이 불완전한 것**입니다.
MP4는 재생에 필요한 색인(`moov`)이 파일 끝에 있어서, 복사가 중간에 끊기면
크기는 그럴듯한데 아무 프로그램도 못 여는 파일이 됩니다. 아이폰이라면 사진
앱에서 **파일 > 내보내기 > 원본 내보내기**로 다시 뽑고, iCloud 다운로드가
끝날 때까지 기다린 뒤 바이트 크기를 비교하세요.

## 실험 세팅 요령

- 자석에 **배경에 없는 단색 표식**(빨강·형광 스티커)을 붙이면 세그멘테이션이
  훨씬 안정적입니다. 실험대에 같은 색 물건을 두지 마세요.
- 웹캠은 **스윙 평면에 수직**으로, 삼각대에 고정. 흔들리면 픽셀 좌표가 통째로
  움직입니다.
- 조명은 일정하게. 형광등 깜빡임이 심하면 셔터가 짧은 카메라를 쓰세요.
- 코일은 **최하점이 아니라 회전점 근처**에 — 이것이 속도와 위치를 분리하는
  핵심 장치입니다.
- 길이 보정: 화면 안에 **자(ruler)나 길이를 아는 물체**를 함께 찍고,
  웹 UI에서 그 구간을 드래그한 뒤 실제 길이(mm)를 입력하세요.
- 촬영한 카메라의 **실제 fps**를 웹 UI의 "추적 fps"에 맞추세요. 폰 카메라는
  촬영 중 프레임레이트가 미세하게 흔들릴 수 있는데(가변 프레임레이트), 이
  분석은 브라우저가 각 프레임에서 실제로 보고하는 시각을 쓰므로 대체로
  괜찮지만, 지정한 fps가 실제와 크게 다르면 프레임을 건너뛰거나 중복 추적할
  수 있습니다.

## 잘 안 될 때

| 증상                                          | 확인할 것                                                                                                                                                                                                                                                |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 검출률이 낮다 (`detected in only …%`)         | S/V 하한을 낮추고 H 범위를 넓히세요. `--min-area`도 줄여보세요                                                                                                                                                                                           |
| 덩어리가 여러 개 잡힌다                       | 검색 영역(ROI) 지정, 또는 H 범위를 좁히기                                                                                                                                                                                                                |
| `LED never crossed the on-threshold`          | LED 영역이 LED를 제대로 덮는지 확인. 안 되면 `--t0-video`/"수동 t₀"로 지정                                                                                                                                                                               |
| `LED region is bright in every frame`         | LED가 켜진 뒤에 녹화를 시작한 경우. **녹화를 먼저 시작**하고 아두이노를 리셋하세요                                                                                                                                                                       |
| `records do not overlap`                      | 전압 로그와 영상이 다른 시행의 것이거나 t₀가 잘못됨                                                                                                                                                                                                      |
| ℰ/v가 회전점에서 폭발한다                     | 정상입니다(v→0). `--v-min`을 올리세요                                                                                                                                                                                                                    |
| 속도 곡선이 톱니처럼 떨린다                   | `--smooth` 값을 키우세요(프레임 수, 홀수)                                                                                                                                                                                                                |
| 웹 UI에서 영상이 안 열린다                    | 메시지가 **"색인(moov)이 없다"** 면 코덱이 아니라 **파일이 옮기다 잘린 것**입니다 — 형식을 바꿔도 소용없고, 원본을 다시 받아야 합니다(이메일 첨부·카카오톡 대용량 전송이 흔한 원인). 그 외의 메시지면 진짜 코덱 문제이니 H.264(mp4)로 다시 내보내 보세요 |
| 웹 UI에서 추적이 오래 걸린다                  | 영상이 길거나 해상도가 큰 경우입니다. 검색 영역(ROI)을 지정하면 빨라집니다                                                                                                                                                                               |
| "경로로 열기"/서버 업로드가 안 보인다         | 공개 배포(`FARADAYCV_LOCAL_MODE=0`)에서는 의도적으로 꺼져 있습니다. 브라우저 추적을 쓰세요                                                                                                                                                               |
| `cannot read that video`                      | `python3 -m faradaycv doctor 파일` 로 원인을 먼저 확인하세요 (CLI/로컬 전용 기능)                                                                                                                                                                        |
| `moov atom is missing` / `Invalid data found` | 코덱이 아니라 **잘린 파일**입니다. 원본을 다시 내보내거나 다시 복사하세요                                                                                                                                                                                |
| `zsh: command not found: pip`                 | macOS에는 `pip` 명령이 없습니다. `python3 -m pip` 를 쓰세요                                                                                                                                                                                              |
| `No module named 'flask'` / `'cv2'`           | 설치를 건너뛴 경우입니다. 위 **설치** 절차(venv + `python3 -m pip install -r requirements.txt`)                                                                                                                                                          |
| `No module named faradaycv`                   | `faraday-cv` 폴더 밖에서 실행한 경우입니다                                                                                                                                                                                                               |
| `zsh: command not found: #`                   | 명령 뒤 주석까지 복사한 경우입니다. zsh는 대화형에서 `#`을 주석으로 보지 않습니다                                                                                                                                                                        |
| `externally-managed-environment`              | 시스템 파이썬에 직접 설치하려 한 경우. venv를 만들거나 `--user` 를 붙이세요                                                                                                                                                                              |

## 개발

```bash
python3 -m pip install -r requirements.txt   # CLI/로컬 웹 전체 기능 (OpenCV 포함)
python3 -m pytest -q
node tests/browser/cv.test.mjs               # 브라우저 컬러 세그멘테이션 단위 테스트
ruff check faradaycv tests
ruff format --check faradaycv tests
```

Python 쪽은 합성 데이터의 정답값과 대조하는 테스트입니다. 매번 영상을 실제로
인코딩·디코딩해서 돌리고, OpenCV 추적 오차 1.5 px 이내·속도 오차 0.05 m/s 이내·
LED 프레임 정확 일치·전압 정점 20 ms 이내, 그리고 "속도 최대 ≠ 전압 최대"라는
논문의 결론까지 검증합니다. `requirements-web.txt`만 설치한(OpenCV 없는) 환경에서
분석 파이프라인이 그대로 동작하는지도 확인합니다.

브라우저 쪽(`static/cv.js`)은 Node로 바로 도는 순수 단위 테스트로 검증하고,
Playwright가 설치돼 있으면(`pip install playwright && playwright install
chromium`) `tests/browser/test_e2e.py` 가 실제 (헤드리스) 브라우저로 페이지를
끝까지 조작해 서버 결과까지 확인합니다 — 없으면 조용히 건너뜁니다. 이 테스트
환경의 헤드리스 크로미움에는 H.264 디코더가 없어서 대안 코덱으로 우회하는데,
그 과정에서 측정된 추적 정밀도 관련 사항은 `tests/browser/README.md` 에
정직하게 적어 두었습니다 — 실사용 브라우저(H.264 지원)에서는 해당하지 않을
가능성이 높은, 이 테스트 환경 고유의 한계입니다.

```
faradaycv/
  track.py          영상 소스와 무관한 추적 결과 모델 (cv2 불필요)
  segmentation.py   HSV 색 범위, 마스크 정리, 덩어리 선택, 클릭→색 추정 (OpenCV, 지연 임포트)
  video.py          OpenCV로 영상 디코딩 + 추적 (CLI/로컬 전용)
  decode.py         재생 안 되는 영상 진단, 필요 시 H.264로 자동 변환 (CLI/로컬 전용)
  voltage.py        아두이노 CSV 파서 (단위·구분자·헤더 자동 판별)
  analysis.py       픽셀→미터 보정, 평활·미분, 시간축 동기화, ℰ/v
  plots.py          논문용 Fig. 2 / Fig. 3 / 진단 그래프
  pipeline.py       추적 결과 → 분석 → 파일 출력 (OpenCV 불필요)
  webapp.py         웹 백엔드: /api/analyze(경량, 공개 배포용) + 서버측 처리(로컬 전용)
  synthetic.py      합성 데이터 생성기 (데모 + 테스트 정답값, H.264로 인코딩)
  cli.py            명령줄
static/
  cv.js             브라우저 컬러 세그멘테이션 (segmentation.py의 JS 버전)
  tracker.js         <video> 프레임 순회 + 전체 추적 루프
  app.js, style.css, index.html   웹 UI
arduino/faraday_logger/   ADS1115 + LED 마커 스케치
tools/serial_logger.py    시리얼 → CSV 저장
wsgi.py, Dockerfile, fly.toml   배포용
../render.yaml   Render Blueprint (저장소 루트에 위치 -- Render가 그곳에서 찾음)
```
