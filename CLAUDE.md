# MPC (Osu!Mania MPC / by Tamania)

osu!mania 맵팩 제작 도구. 레퍼런스는 `Desktop/MapPackCreator`(구형, 대체 대상), `Desktop/osu-trainer-v1.8.0`,
`Desktop/Osu Rate Changer`, Companella(`%LOCALAPPDATA%\Companella`, 소스 github.com/leyna64/companella 브랜치 `live`).

## 오너가 정한 것 (2026-11-12 첫 요청)
- 표기명 `Osu!Mania MPC`, 부제 `by Tamania` (0.2.0에서 `Map Pack Create`에서 변경). 바탕색 `#111111`.
  데이터 폴더 이름은 `MapPackCreate` 그대로 둔다(저장된 팩 구성 유지).
- 완성본은 `output/` 폴더만 보면 되게 한다 (`Osu!Mania MPC.exe`).
- 창 3개: 맵 고르기 / 썸네일 / 메타데이터.
  - 맵 고르기: 고른 맵의 썸네일·예상 난이도·길이·제작자·난이도명 표시, 배속을 바(소수점 둘째 자리)로 정해 하나씩 넣기.
    예상 난이도 옆 느낌표에 "100% 신뢰하지 말고 참고용" 문구. 목적은 팩 안에서 난이도가 튀는 맵 방지.
    피치 유지 / 배속에 따라 변경 체크박스.
  - 썸네일: 16:9 강제, 심볼·이미지를 이미지 편집기처럼 자유 배치, 노이즈 등 효과를 모든 맵에 동시 적용,
    .jpg/.png 통일 선택 + png 용량 경고 문구.
  - 메타데이터: BeatmapID 미업로드 상태로, Tags 통일, 팩 이름, 맵별 diff name 직접 입력,
    delete 난이도 자동 추가(썸네일 선택, 미리듣기 음악: 별도 추가 / 팩 안의 음악 / 없음).
- 모든 음원은 .mp3로 변환, 오프셋 손실·밀림이 없어야 한다.
- 내보내기 때 업로드 순서 안내 문구를 **오너가 준 문장 그대로** 띄운다 (`index.html`의 `.guide-note`, README).
- 진행 방식: 첫 버전 → 오너가 버그·동작 테스트 → 다음 수정.
- 0.1.1 (2026-11-12 오너 첫 테스트): **osu!에서 고른 맵이 자동으로 프로그램에 떠야 한다** (구 MapPackCreator처럼).
  목록 검색은 보조 수단. 기본으로 켜져 있고 왼쪽 위 체크박스로 끈다.

- 0.2.0 (2026-11-12 오너 2차 요청, 0.1.1 동작 확인 후):
  - 탭: 맵 고르기 / **팩 구성** / 썸네일 / 메타데이터 + 따로 떨어진 **레이트 체인저**.
  - 맵 목록(왼쪽)은 기본으로 접어 둔다. 대부분 osu! 따라가기로 고르기 때문 (설정 `libOpen`).
  - 느낌표 아이콘은 옆 글자와 크기 대비를 맞춘다(14px 원, 글자 13px). 툴팁은 화면에 떠 있는 하나(`#tipFloat`, `data-tip`).
  - 롱놋: 섞여 있으면 단놋/롱놋 단위인정을 함께, 전부 롱놋이면 롱놋 먼저 + 단놋 작게 (`packInfo().mode` = rice/ln/mixed).
  - 썸네일: "이 맵만" 심볼 변경(`entry.symbols[layerId]`)·효과 변경(`entry.fx`), 심볼 색조 돌리기·색 입히기, jpg 품질 기본 100,
    [delete] 칸은 옅은 글로우 + 느낌표 설명, 커스텀 단위인정 심볼(설정 `customSymbols`, 이름 끝 ++ + - -- 로 단계 분류,
    기존 심볼 이름과 겹치면 거부, 삭제 가능).
  - 팩 구성: 맨 위에 메타데이터의 팩 이름, 맵마다 단위인정 위치를 선 그래프로, 점을 누르면 썸네일과 이름.
  - 레이트 체인저: 맵 하나를 n.x~n.x 배속으로, 배속별 예상 난이도 표시, 특정 배속부터 썸네일·효과 변경,
    난이도명 방식 선택(뒤에 `1.1` / `1.1x` / 직접 규칙 / 정배속 아닌 것은 배속만).

- 0.3.0 (2026-11-12 오너 3차 요청, 레이트 체인저 동작 확인 후):
  - 시작할 때 이전 작업이 있으면 "이어서 하기 / 처음부터 새로 만들기"를 묻는다 (`askResume`; Esc는 이어서 하기).
    처음부터를 고르면 지우기 전에 `project.backup.json`으로 한 벌 남긴다. `#view=`로 바로 여는 경우는 묻지 않는다(개발용).
  - 메타데이터 "모두 지우기", 넣은 맵 "모두 빼기". 확인 창을 거친다.
  - **삭제·지우기 버튼은 모든 창에서 `.btn.danger`** (붉은색 + 휴지통 아이콘, CSS `::before` 마스크). 새로 만들 때도 이 클래스를 쓴다.
    되돌리기·초기화(원래대로, 효과 초기화 등)는 삭제가 아니므로 붙이지 않았다.
  - 썸네일이 없는 맵은 그림 자리에 "썸네일 없음" (`thumbBox`, 편집기 캔버스는 `render(..., preview=true)`. 내보내는 그림에는 넣지 않는다).
  - **공유용**: `build.ps1`이 `output\Osu!Mania MPC v<버전>.zip`을 만든다 (exe + ffmpeg.exe + README + licenses). 오너는 이 zip만 보내면 된다.

## 구조
- `src/mpc/` 본체, **표준 라이브러리만** 사용.
  - `osudb.py` osu!.db 파싱(mania만) + db에 없는 Songs 폴더는 직접 읽기. 읽기 전용.
  - `osufile.py` .osu 읽기/변환(배속, 메타데이터 통일, delete 난이도 생성). 스토리보드·비디오 이벤트는 버린다.
    노트·타이밍 포인트·브레이크는 같은 반올림(`rnd`)으로 정수 ms로 맞춘다(순서가 뒤집히지 않게).
  - `audio.py` ffmpeg 호출, 오프셋 측정·보정 (아래 "오디오" 참고).
  - `live.py` 실행 중인 osu!stable 메모리에서 고른 맵의 MD5·화면 상태·폴더/파일명 읽기 (MMR의 것 + 폴더/파일명
    `beatmap+0x78`/`+0x90`). 읽기 전용. osu!.db에 아직 없는 맵은 그 폴더를 직접 읽어 목록에 넣는다(`Library.adopt`).
  - `calc.py` 예상 난이도: MMR 프로젝트의 `mmr-calc.exe`(Mania Tracker dan-calc)를 상주 자식 프로세스로 사용.
  - `core.py` 상태, 맵 상세, 내보내기 작업(`ExportJob`). `server.py` 127.0.0.1 서버 + Edge `--app` 창 (MMR과 같은 방식).
  - `web/` 화면: `index.html`, `app.css`, `app.js`(맵 고르기·메타데이터·내보내기, `window.MPC`로 공유),
    `editor.js`(썸네일 렌더·편집기, `window.Thumb`), `parts.js`(팩 구성·레이트 체인저·선 그래프), `dans/`(단 심볼, MIT).
  - 레이트 체인저 내보내기는 `core.RateJob`(ExportJob 상속). 원본 맵 폴더에 쓸 때는 **기존 파일을 절대 덮어쓰지 않고**
    (이름이 겹치면 `_2`, 난이도명은 `(2)`), 실패·취소 시 자기가 만든 파일(`job.created`)만 지운다. 1.00배속은 원본 오디오를 그대로 가리킨다.
  - `bin/mmr-calc.exe` MMR의 calc 크레이트(`../maniatracker/calc`)를 `tools/build_calc.ps1`로 빌드한 것 (0.3.0부터).
    MMR의 `calc/bin` 것을 그대로 복사하면 **안 된다**: 그 빌드에는 `C:\Users\<계정>\.cargo\...` 경로가 119곳 박혀 있어
    공유본에 Windows 계정 이름이 새어 나간다. `build_calc.ps1`은 `--remap-path-prefix`로 가린다 (소스·고정 커밋·플래그는 같음,
    `tests/compare_calc.py`로 결과가 같은지 확인). 공유 전 점검: `python tools/scan_private.py src/mpc/bin/mmr-calc.exe`.
    Python 쪽은 PyInstaller가 경로를 지워 주므로 문제없다(확인함).
- 썸네일은 브라우저 canvas에서 그린다(`Thumb.render`). 미리보기·필름스트립·내보내기가 같은 함수를 쓴다.
  내보낼 때 화면이 맵마다 그려서 `/api/export/image`로 올리고, 그다음 서버가 오디오와 .osu를 만든다.
- `build.ps1` → PyInstaller onefile `output/Map Pack Create.exe`(약 12MB) + `output/ffmpeg.exe`(Companella 것 복사, 105MB,
  exe 안에 넣지 않음: 실행마다 100MB를 푸는 것을 피하려고) + `output/README.txt`. 내보낸 팩은 기본 `output/packs/`.
- 데이터: `%LOCALAPPDATA%\MapPackCreate` (settings.json, project.json 자동 저장, assets\ 사용자가 넣은 이미지·음악, logs\).

## 디자인 (anthropics/skills의 frontend-design을 기준으로 선택. MMR과 같은 원칙)
- 크롬은 순수 무채색(`#111111` 바닥). 색은 데이터(단 심볼, 맵 배경, 경고 노랑)에만. 숫자는 Bahnschrift.
- 시그니처는 배속 눈금자(0.50~2.00, 0.01 단위). 팩 구성 위의 "난이도 분포" 띠가 튀는 맵을 노랗게 표시(중앙값에서 1단 초과).
- 파일에서 온 문자열은 `textContent`로만 넣는다. 웹폰트·CDN 금지.

## 오디오 (2026-11-12 실측, ffmpeg 9.0.2 + BASS 2.4.17 = Companella에 든 것)
- LAME 태그가 있는 mp3는 ffmpeg와 BASS가 0.02ms로 일치 → ogg/flac → mp3는 오프셋 불변.
- **태그 없는 mp3**: BASS는 디코더 지연 529샘플을 버리고 ffmpeg는 안 버린다(12ms 차이) → 그런 소스는 `atrim=start_sample=529`.
  판별은 ffmpeg가 보고하는 `start:` 값이 0인지로 한다.
- 1.00배속 mp3는 파일 복사. 피치 변경 배속은 `asetrate`(샘플 정확).
- 피치 유지 배속: `atempo`는 7~15ms, `rubberband` 기본 창은 2~9ms 밀리고 구간 편차도 크다 → `rubberband window=short`
  (편차 1~3ms)로 늘린 뒤, 정확한 타임라인(asetrate 결과)과 onset 포락선을 7개 구간에서 교차상관해 밀림을 재고
  잘라내거나 무음을 붙여 보정, 완성된 mp3로 다시 재서 결과 화면에 표시. 독립 측정(numpy)으로 ±0.7ms 이내 확인.
- Companella는 원본 확장자를 유지하고 보정이 없다 (RateChanger.cs: asetrate / atempo, `-q:a 0`).
- **osu! 자체 디코더로 확인함 (0.1.1)**: osu! 폴더의 `bass.dll`(숨김 파일, 32비트, 2.4.15.2)을 `tests/bass_probe.cs`
  (csc `/platform:x86`)로 불러 같은 파일을 디코드 → BASS 2.4.17과 결과가 같다. 프로그램이 만든 mp3를 그걸로 재면
  변환·피치 변경은 0.02ms, 피치 유지는 0.5~1.2ms(잡음 속 클릭 신호, 가장 불리한 경우).

## 프로그램 종료 판단 (0.1.0의 치명적 버그)
- 0.1.0은 MMR처럼 "브라우저 실행 프로세스가 끝났고 6초간 조용하면 종료"했다. 오너 PC에서 Edge는 창을 다른 프로세스에
  넘기고 실행 프로세스가 바로 끝나므로, 창이 떠 있는데 서버가 10초 만에 종료 → 맵을 눌러도 "파일을 찾지 못했습니다".
- 지금은 화면이 `/api/hold` 연결 하나를 계속 열어 두고(5초마다 ping도 보냄), 그 연결이 닫히고 20초간 조용할 때만 종료한다.
  실행 프로세스(`window.poll()`)는 보지 않는다. 서버가 죽으면 화면에 "연결이 끊어졌습니다" 안내가 뜬다.
- 창 실행 옵션에 타이머 절전 해제 플래그를 넣었다(osu! 뒤에 가려져 있어도 따라가기가 돌도록).
- 확인: `tests/test_app.py`, 그리고 `tests/run_hidden.py`로 실제 exe를 보이지 않는 데스크톱에서 실행해 로그의
  `window connected` / `window gone` 확인. 주의: onefile exe는 부모·자식 두 프로세스라 TerminateProcess로는 자식이 남는다
  → 끝나면 `taskkill /IM "Osu!Mania MPC.exe" /F`, Edge는 명령줄에 테스트 데이터 폴더가 든 것만 골라 종료.

## 명령
- 테스트: `python tests/test_core.py` (변환 규칙 + 실제 맵으로 임시 폴더에 내보내기),
  `python tests/test_rate.py` (레이트 체인저: 맵을 임시 Songs 폴더에 복사해 원본 무변경 확인),
  `python tests/test_app.py` (종료 판단 + osu! 따라가기, `tests/fake_osu.py`가 osu! 역할)
- 오디오 정확도 점검: `python tests/check_audio.py <오디오 파일>` (numpy 필요, 개발용)
- 화면 확인: `.claude/launch.json`의 `mpc-dev` → `http://127.0.0.1:8791/?t=dev` (`localhost`는 Host 검사에 막힘). 데이터·내보내기는 `%TEMP%\mpc-dev`.
  그 폴더에 `live.txt`가 있으면 가짜 osu! 신호로 쓴다 (md5 / `none` / `off`를 적는다).
  Browser 창이 가려져 캡처가 안 될 때: `python tools/shot.py <pick|pack|thumb|meta|rate> <out.png>` (헤드리스 Edge, `#view=`로 그 파트를 연다).
  개발 서버에서 레이트 체인저를 시험할 때는 반드시 "packs 폴더에 따로 만들기"로 (원본 폴더 = 실제 osu! Songs).
- 빌드: `powershell -ExecutionPolicy Bypass -File build.ps1` (exe + licenses + 공유용 zip)
- 공유본 점검: `python tests/check_share.py` (zip을 다른 곳에 풀어 새 사용자처럼 실행. 프로그램이 켜져 있으면 거부한다)
- exe 점검(창 없이): `MPC_NO_WINDOW=1 MPC_PORT=... MPC_TOKEN=... MPC_DATA_DIR=... MPC_PACKS_DIR=...`로 실행 후 API 호출.

## 아직 안 한 것 / 가정
- delete 난이도: 오디오 = 설정 분 + 5초, 노트 2개(1초, 설정 분 + 1초). 마라톤 인식 기준 시간은 확인하지 못했다(오너 말 "10분"을 기본값으로).
- osu! 따라가기와 목록 선택은 오너가 실제 osu!에서 동작을 확인했다 (2026-11-12, 0.1.1).
  문제가 생기면 `%LOCALAPPDATA%\MapPackCreate\logs`의 `mpc.live` 줄(osu! found / memory located / signature not found)을 본다.
- Windows 탐색 주의: osu! 폴더의 dll들은 숨김 속성이라 `Get-ChildItem`에 `-Force`가 없으면 안 보인다.
- 커스텀 히트사운드 파일은 복사하지 않는다.
- 실제 업로드(BSS) 흐름은 오너 확인이 필요하다.
- 레이트 체인저의 "원본 맵 폴더에 추가"는 임시 폴더 복사본으로만 시험했다. CSS 클래스 이름 주의: `.top`, `.rate`는
  이미 다른 뜻으로 쓰여 두 번 충돌했다 (레이트 체인저 뷰는 `.ratev`).
