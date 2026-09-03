# faraday-cv

패러데이 법칙 진자 실험용 **컬러 세그멘테이션 영상 분석 도구**.

웹캠으로 찍은 진자 자석 영상에서 색으로 자석을 추적해 **위치·순간속도**를 뽑고,
따로 업로드한 **아두이노 전압 로그**를 LED 타이밍 신호로 동기화해서, 하나의
시간축 위에 논문용 그래프를 그립니다.

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

## 설치

가상환경을 만들어 설치하는 것을 권합니다 (macOS 기본 파이썬에서 `pip install`이
`externally-managed-environment` 오류를 내는 것을 피할 수 있습니다).

```bash
cd faraday-cv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

- 두 번째 실행부터는 `source .venv/bin/activate` 한 줄이면 됩니다.
- Windows는 `python3` 대신 `py`, 활성화는 `.venv\Scripts\activate`.
- macOS·Linux에 `pip` 명령이 없어도 됩니다. 항상 `python3 -m pip` 를 쓰세요.
- 아래 명령들은 **`faraday-cv` 폴더 안에서** 실행합니다.
  `No module named faradaycv` 오류는 대부분 다른 폴더에 있다는 뜻입니다.

## 1분 체험 (장비 없이)

합성 데이터셋(영상 + 전압 로그 + 정답값)을 만들어서 전체 흐름을 그대로 돌려봅니다.
첫 명령이 `example-data/pendulum.mp4` 와 `voltage.csv` 를 만듭니다.

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
max speed       : 0.676 m/s at t = 1.724 s
max |emf|       : 20.61 mV at t = 1.534 s
peak separation : -0.190 s (speed at the emf peak: 0.455 m/s)
```

최대 속도 시각과 최대 전압 시각이 **0.19초 어긋나 있고**, 전압이 최대인 순간의
속도는 최대 속도의 67 %, 반대로 속도가 최대일 때 전압은 정점의 7 %밖에 안 됩니다.
논문이 말하는 바로 그 결과입니다.

> 스윙이 여러 번 들어간 기록에서는 최대 속도 지점이 여러 개라서, 비교에 쓰는
> "최대 속도 시각"은 **전압 정점에 가장 가까운** 최대 속도 지점으로 잡습니다.

## 웹 UI (코딩 없이)

```bash
python3 -m faradaycv serve
```

터미널에 뜨는 주소(기본 `http://127.0.0.1:8000`)를 브라우저에서 열고, 끌 때는
터미널에서 `Ctrl+C`. 포트가 이미 쓰이면 `--port 8080` 처럼 바꾸세요.

브라우저에서 순서대로:

1. **영상 업로드** — mp4/mov/avi 등. 용량이 큰 영상은 업로드 대신
   **파일 경로**(`/Users/이름/Movies/swing.mp4`)를 입력해 바로 열 수 있습니다.
   같은 컴퓨터에서 도는 도구라 복사 없이 원본을 그대로 읽습니다
2. **자석 클릭** → HSV 범위 자동 설정, 슬라이더로 미세조정
   (초록색으로 칠해진 부분이 "자석으로 인식된 픽셀")
3. **코일 위치 클릭**, **길이 보정 드래그**(아는 길이를 mm로 입력),
   **LED 영역 드래그**
4. **아두이노 전압 파일 업로드** — 영상과 별개로 따로 올립니다
5. **분석 실행** → 그래프 2장 + 진단 그래프, CSV 다운로드

세그멘테이션이 잘 안 될 때는 ⑤ **검색 영역**을 드래그해 자석이 지나가는
구역만 남기면 배경의 비슷한 색을 무시할 수 있습니다.

## 명령줄

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

- mp4·mov·avi·mkv 등을 그대로 올리면 됩니다.
- **아이폰 영상(HEVC/H.265)** 은 OpenCV가 못 읽는 경우가 많습니다. 그럴 때는
  같이 설치된 ffmpeg로 **H.264 고정 프레임레이트 사본을 자동 생성**해서
  분석합니다. 첫 업로드 때 한 번만 시간이 걸리고(길이에 따라 수십 초),
  변환본은 임시 폴더에 캐시되어 다음부터는 즉시 열립니다.
- 변환은 **가변 프레임레이트(VFR)** 문제도 함께 해결합니다. 폰 카메라는 VFR로
  녹화하는 경우가 많은데, 이 분석은 프레임 시각을 `프레임번호 / fps` 로 계산하므로
  고정 프레임레이트여야 정확합니다. 가능하면 촬영 자체를 고정 fps로 하세요.
- 직접 변환하고 싶으면:

```bash
ffmpeg -i 원본.mp4 -c:v libx264 -pix_fmt yuv420p -an swing.mp4
```

- 영상이 안 열리면 **원인부터 확인**하세요. 코덱 문제인지, 파일이 잘린 것인지,
  아예 동영상이 아닌지를 구분해 알려줍니다:

```bash
python3 -m faradaycv doctor /경로/swing.mp4
```

`moov atom is missing` 이 나오면 코덱이 아니라 **파일이 불완전한 것**입니다.
MP4는 재생에 필요한 색인(`moov`)이 파일 끝에 있어서, 복사나 업로드가 중간에
끊기면 크기는 그럴듯한데 아무 프로그램도 못 여는 파일이 됩니다.
아이폰이라면 사진 앱에서 **파일 > 내보내기 > 원본 내보내기**로 다시 뽑고,
iCloud 다운로드가 끝날 때까지 기다린 뒤 바이트 크기를 비교하세요.

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

## 잘 안 될 때

| 증상                                          | 확인할 것                                                                                       |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 검출률이 낮다 (`detected in only …%`)         | S/V 하한을 낮추고 H 범위를 넓히세요. `--min-area`도 줄여보세요                                  |
| 덩어리가 여러 개 잡힌다                       | 검색 영역(ROI) 지정, 또는 H 범위를 좁히기                                                       |
| `LED never crossed the on-threshold`          | LED 영역이 LED를 제대로 덮는지 확인. 안 되면 `--t0-video`로 수동 지정                           |
| `LED region is bright in every frame`         | LED가 켜진 뒤에 녹화를 시작한 경우. **녹화를 먼저 시작**하고 아두이노를 리셋하세요              |
| `records do not overlap`                      | 전압 로그와 영상이 다른 시행의 것이거나 t₀가 잘못됨                                             |
| ℰ/v가 회전점에서 폭발한다                     | 정상입니다(v→0). `--v-min`을 올리세요                                                           |
| 속도 곡선이 톱니처럼 떨린다                   | `--smooth` 값을 키우세요(프레임 수, 홀수)                                                       |
| `cannot read that video`                      | `python3 -m faradaycv doctor 파일` 로 원인을 먼저 확인하세요                                    |
| `moov atom is missing` / `Invalid data found` | 코덱이 아니라 **잘린 파일**입니다. 원본을 다시 내보내거나 다시 복사하세요                       |
| `the upload was cut short`                    | 업로드가 끊겼습니다. 다시 시도하거나 **경로로 열기**를 쓰세요                                   |
| `zsh: command not found: pip`                 | macOS에는 `pip` 명령이 없습니다. `python3 -m pip` 를 쓰세요                                     |
| `No module named 'flask'` / `'cv2'`           | 설치를 건너뛴 경우입니다. 위 **설치** 절차(venv + `python3 -m pip install -r requirements.txt`) |
| `No module named faradaycv`                   | `faraday-cv` 폴더 밖에서 실행한 경우입니다                                                      |
| `zsh: command not found: #`                   | 명령 뒤 주석까지 복사한 경우입니다. zsh는 대화형에서 `#`을 주석으로 보지 않습니다               |
| `externally-managed-environment`              | 시스템 파이썬에 직접 설치하려 한 경우. venv를 만들거나 `--user` 를 붙이세요                     |

## 개발

```bash
python3 -m pytest -q
ruff check faradaycv tests
ruff format --check faradaycv tests
```

합성 데이터의 정답값과 대조하는 79개 테스트입니다.

테스트는 매번 영상을 실제로 인코딩·디코딩해서 돌립니다. 추적 오차 1.5 px 이내,
속도 오차 0.05 m/s 이내, LED 프레임 정확 일치, 전압 정점 20 ms 이내 —
그리고 "속도 최대 ≠ 전압 최대"라는 논문의 결론까지 검증합니다.

```
faradaycv/
  segmentation.py   HSV 색 범위, 마스크 정리, 덩어리 선택, 클릭→색 추정
  video.py          영상 1회 디코딩으로 자석 추적 + LED 신호 동시 취득
  voltage.py        아두이노 CSV 파서 (단위·구분자·헤더 자동 판별)
  analysis.py       픽셀→미터 보정, 평활·미분, 시간축 동기화, ℰ/v
  plots.py          논문용 Fig. 2 / Fig. 3 / 진단 그래프
  pipeline.py       전체 실행과 파일 출력
  webapp.py         노코드 웹 UI (Flask)
  synthetic.py      합성 데이터 생성기 (데모 + 테스트 정답값)
  cli.py            명령줄
arduino/faraday_logger/   ADS1115 + LED 마커 스케치
tools/serial_logger.py    시리얼 → CSV 저장
```
